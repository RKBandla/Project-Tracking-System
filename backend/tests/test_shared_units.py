"""Unit tests for shared helpers: auth, validation, query building and HTTP parsing."""

import base64
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import jwt
import pytest

from shared import auth
from shared.errors import ApiError
from shared.http import Request, Router, normalise_path, response
from shared.query import Filters, like_pattern, order_by, pagination
from shared.users import can_view_salary, serialize_user
from shared.validation import Field, check_date_range, validate


class TestAuth:
    def test_generated_password_is_six_alphanumeric_with_letter_and_digit(self):
        for _ in range(200):
            password = auth.generate_password()
            assert len(password) == 6
            assert password.isalnum()
            assert any(c.isalpha() for c in password) and any(c.isdigit() for c in password)

    def test_hash_and_verify(self):
        encoded = auth.hash_password("abc123")
        assert encoded.startswith("pbkdf2_sha256$")
        assert "abc123" not in encoded
        assert auth.verify_password("abc123", encoded)
        assert not auth.verify_password("abc124", encoded)

    def test_hashes_are_salted(self):
        assert auth.hash_password("abc123") != auth.hash_password("abc123")

    @pytest.mark.parametrize("bad", ["", "nonsense", "md5$1$a$b", "pbkdf2_sha256$x$y$z"])
    def test_verify_rejects_malformed_hashes(self, bad):
        assert not auth.verify_password("abc123", bad)

    def test_token_round_trip(self):
        tokens = auth.issue_tokens({"id": 7, "role": "manager"})
        assert auth.decode_token(tokens["access_token"], "access") == 7
        assert auth.decode_token(tokens["refresh_token"], "refresh") == 7

    def test_token_type_is_enforced(self):
        tokens = auth.issue_tokens({"id": 7, "role": "manager"})
        with pytest.raises(ApiError) as err:
            auth.decode_token(tokens["refresh_token"], "access")
        assert err.value.status == 401

    def test_expired_token(self):
        past = datetime.now(timezone.utc) - timedelta(hours=2)
        token = jwt.encode({"sub": "1", "type": "access", "exp": past}, auth._secret(), algorithm="HS256")
        with pytest.raises(ApiError, match="expired"):
            auth.decode_token(token, "access")

    def test_tampered_token(self):
        token = jwt.encode({"sub": "1", "type": "access"}, "wrong-secret", algorithm="HS256")
        with pytest.raises(ApiError, match="Invalid token"):
            auth.decode_token(token, "access")

    @pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer ", "Bearer"])
    def test_bearer_token_required(self, header):
        headers = {} if header is None else {"authorization": header}
        with pytest.raises(ApiError) as err:
            auth.bearer_token(headers)
        assert err.value.status == 401

    def test_secret_required_outside_local(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "")
        monkeypatch.setenv("IS_LOCAL", "false")
        with pytest.raises(RuntimeError):
            auth._secret()


class TestValidation:
    SCHEMA = {
        "name": Field(required=True, max_length=5),
        "email": Field(kind="email"),
        "count": Field(kind="int", min_value=1, max_value=40),
        "amount": Field(kind="decimal", min_value=0),
        "when": Field(kind="date", nullable=True),
        "flag": Field(kind="bool"),
        "color": Field(choices=("red", "blue")),
    }

    def test_valid_input_is_cleaned(self):
        out = validate({"name": " Bob ", "email": "A@B.COM", "count": "3", "amount": 1.5,
                        "when": "2026-01-02", "flag": True, "color": "red"}, self.SCHEMA)
        assert out == {"name": "Bob", "email": "a@b.com", "count": 3, "amount": Decimal("1.50"),
                       "when": date(2026, 1, 2), "flag": True, "color": "red"}

    def test_all_errors_reported_together(self):
        with pytest.raises(ApiError) as err:
            validate({"name": "toolong", "email": "nope", "count": 41, "amount": -1, "when": "x",
                      "flag": "yes", "color": "green", "extra": 1}, self.SCHEMA)
        details = err.value.details
        assert err.value.status == 400
        assert set(details) == {"name", "email", "count", "amount", "when", "flag", "color", "extra"}

    def test_required(self):
        with pytest.raises(ApiError) as err:
            validate({}, self.SCHEMA)
        assert err.value.details == {"name": "is required"}

    def test_partial_skips_missing_fields(self):
        assert validate({"count": 2}, self.SCHEMA, partial=True) == {"count": 2}

    @pytest.mark.parametrize("value", [True, 1.5, "abc", None])
    def test_int_rejects_non_integers(self, value):
        schema = {"n": Field(kind="int", required=True)}
        with pytest.raises(ApiError):
            validate({"n": value}, schema)

    @pytest.mark.parametrize("value", [True, "abc", "NaN", "Infinity"])
    def test_decimal_rejects_non_numbers(self, value):
        with pytest.raises(ApiError):
            validate({"amount": value}, {"amount": Field(kind="decimal")})

    def test_string_type_enforced(self):
        with pytest.raises(ApiError):
            validate({"name": 5}, self.SCHEMA)

    def test_date_range(self):
        check_date_range(date(2026, 1, 1), date(2026, 1, 1))
        check_date_range(None, date(2026, 1, 1))
        with pytest.raises(ApiError) as err:
            check_date_range(date(2026, 2, 1), date(2026, 1, 1))
        assert "end_date" in err.value.details


class TestQuery:
    def test_like_pattern_escapes_wildcards(self):
        assert like_pattern("50%_off\\") == "%50\\%\\_off\\\\%"

    def test_filters(self):
        f = Filters().eq("a", 1).eq("b", None).search(["x", "y"], " term ")
        assert f.where() == "WHERE a = %s AND (x ILIKE %s OR y ILIKE %s)"
        assert f.params == [1, "%term%", "%term%"]
        assert Filters().where() == ""

    def test_order_by(self):
        allowed = {"name": "name", "due": "due_date"}
        assert order_by({}, allowed, "name") == "ORDER BY name ASC NULLS LAST, id ASC"
        assert order_by({"sort": "-due"}, allowed, "name") == "ORDER BY due_date DESC NULLS LAST, id DESC"
        with pytest.raises(ApiError):
            order_by({"sort": "password_hash"}, allowed, "name")

    def test_pagination(self):
        assert pagination({}) == (1, 20)
        assert pagination({"page": "3", "page_size": "50"}) == (3, 50)
        for bad in ({"page": "0"}, {"page_size": "101"}, {"page": "x"}):
            with pytest.raises(ApiError):
                pagination(bad)


class TestHttp:
    @pytest.mark.parametrize("raw,expected", [
        ("/api/projects", "/"), ("/api/projects/", "/"), ("/api/projects/5", "/5"),
        ("/api/projects/5/archive/", "/5/archive"), ("/5", "/5"), ("/", "/"), ("", "/"),
        ("/api/projects-other/5", "/api/projects-other/5"),
    ])
    def test_normalise_path(self, raw, expected):
        assert normalise_path(raw, "projects") == expected

    def test_request_parsing_base64_body(self):
        event = {"rawPath": "/api/x/1", "requestContext": {"http": {"method": "post"}},
                 "headers": {"Authorization": "Bearer t"}, "isBase64Encoded": True,
                 "body": base64.b64encode(b'{"a": 1}').decode()}
        req = Request.from_event(event, "x")
        assert (req.method, req.path, req.headers["authorization"], req.body) == ("POST", "/1", "Bearer t", {"a": 1})

    @pytest.mark.parametrize("body", ["{bad", "[1, 2]"])
    def test_invalid_body(self, body):
        with pytest.raises(ApiError):
            _ = Request(method="POST", path="/", raw_body=body).body

    def test_router(self):
        router = Router()
        router.get("/")(lambda r, c: "list")
        router.get("/dashboard")(lambda r, c: "dash")
        router.get("/{id}")(lambda r, c: "one")
        req = Request(method="GET", path="/42")
        assert router.match(req).handler(req, None) == "one" and req.params == {"id": 42}
        assert router.match(Request(method="GET", path="/dashboard")).handler(None, None) == "dash"
        with pytest.raises(ApiError) as err:
            router.match(Request(method="DELETE", path="/42"))
        assert err.value.status == 405
        with pytest.raises(ApiError) as err:
            router.match(Request(method="GET", path="/abc"))
        assert err.value.status == 404

    def test_response_serialises_decimal_and_dates(self):
        res = response(200, {"d": Decimal("1.50"), "t": date(2026, 1, 2)})
        assert res["body"] == '{"d": 1.5, "t": "2026-01-02"}'
        assert "body" not in response(204)


class TestUserSerialisation:
    USER = {"id": 5, "first_name": "A", "last_name": "B", "salary_cents": 10, "manager_id": 2,
            "password_hash": "secret", "role": "employee"}

    @pytest.mark.parametrize("viewer,sees", [
        ({"id": 1, "role": "admin"}, True),
        ({"id": 5, "role": "employee"}, True),
        ({"id": 2, "role": "manager"}, True),
        ({"id": 3, "role": "manager"}, False),
        ({"id": 6, "role": "employee"}, False),
    ])
    def test_salary_visibility(self, viewer, sees):
        assert can_view_salary(viewer, self.USER) is sees
        data = serialize_user(self.USER, viewer)
        assert ("salary_cents" in data) is sees
        assert "password_hash" not in data
        assert data["full_name"] == "A B"
