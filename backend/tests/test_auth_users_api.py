"""Integration tests for the auth and users services."""

from shared import db

from .conftest import ADMIN_EMAIL, ADMIN_PASSWORD


class TestAuth:
    def test_login_with_email(self, api):
        res = api.call("auth", "POST", "/login", {"email": "ADMIN@pts.test", "password": ADMIN_PASSWORD})
        assert res.status == 200
        assert res.json["user"]["email"] == ADMIN_EMAIL and res.json["user"]["role"] == "admin"
        assert "password_hash" not in res.json["user"]
        assert res.json["access_token"] and res.json["refresh_token"] and res.json["expires_in"] == 3600

    def test_wrong_password_and_unknown_email_look_identical(self, api):
        wrong = api.call("auth", "POST", "/login", {"email": ADMIN_EMAIL, "password": "nope12"})
        unknown = api.call("auth", "POST", "/login", {"email": "ghost@pts.test", "password": "nope12"})
        assert wrong.status == unknown.status == 401
        assert wrong.json == unknown.json

    def test_login_validation(self, api):
        res = api.call("auth", "POST", "/login", {"email": "not-an-email"})
        assert res.status == 400
        assert set(res.json["error"]["details"]) == {"email", "password"}
        assert api.call("auth", "POST", "/login", raw_body="{nope").status == 400

    def test_refresh_and_token_types(self, api):
        login = api.call("auth", "POST", "/login", {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).json
        assert api.call("auth", "POST", "/refresh", {"refresh_token": login["refresh_token"]}).status == 200
        assert api.call("auth", "POST", "/refresh", {"refresh_token": login["access_token"]}).status == 401

    def test_token_required(self, api, admin):
        assert api.call("auth", "GET", "/me").status == 401
        assert api.call("auth", "GET", "/me", token="garbage").status == 401
        assert api.call("auth", "GET", "/me", token=admin["token"]).json["id"] == admin["id"]

    def test_routing_errors(self, api, admin):
        assert api.call("auth", "GET", "/nope", token=admin["token"]).status == 404
        assert api.call("auth", "DELETE", "/me", token=admin["token"]).status == 405
        assert api.call("auth", "OPTIONS", "/login").status == 204

    def test_deactivated_user_is_locked_out(self, api, admin, make_user):
        emp = make_user()
        assert api.call("users", "PUT", f"/{emp['id']}", {"is_active": False}, token=admin["token"]).status == 200
        assert api.call("auth", "GET", "/me", token=emp["token"]).status == 401
        assert api.call("auth", "POST", "/login", {"email": emp["email"], "password": emp["password"]}).status == 401


class TestUserCreation:
    def test_admin_creates_user_with_generated_credentials(self, api, admin):
        res = api.call("users", "POST", "/", {
            "first_name": "Ada", "last_name": "Lovelace", "email": "ADA@Example.com",
            "job_title": "Engineer", "salary_cents": 8_500_000, "role": "employee",
        }, token=admin["token"])
        assert res.status == 201
        assert res.json["employee_id"] == "EMP0001"
        password = res.json["temporary_password"]
        assert len(password) == 6 and password.isalnum()
        assert res.json["user"]["email"] == "ada@example.com" and res.json["user"]["salary_cents"] == 8_500_000
        with db.cursor() as cur:
            cur.execute("SELECT password_hash FROM users WHERE id = %s", [res.json["user"]["id"]])
            stored = cur.fetchone()["password_hash"]
        assert password not in stored and stored.startswith("pbkdf2_sha256$")
        assert api.login("ada@example.com", password)

    def test_money_must_be_whole_cents(self, api, admin):
        res = api.call("users", "POST", "/", {"first_name": "A", "last_name": "B", "email": "a@b.com",
                                              "job_title": "T", "role": "employee", "salary_cents": 100.5},
                       token=admin["token"])
        assert res.status == 400 and "salary_cents" in res.json["error"]["details"]

    def test_only_admins_create_users(self, api, make_user):
        mgr = make_user(role="manager")
        emp = make_user(manager_id=mgr["id"])
        body = {"first_name": "X", "last_name": "Y", "email": "x@y.com", "job_title": "T", "role": "employee"}
        assert api.call("users", "POST", "/", body, token=mgr["token"]).status == 403
        assert api.call("users", "POST", "/", body, token=emp["token"]).status == 403

    def test_duplicate_email(self, api, admin, make_user):
        make_user(email="dup@example.com")
        res = api.call("users", "POST", "/", {"first_name": "X", "last_name": "Y", "email": "DUP@example.com",
                                              "job_title": "T", "role": "employee"}, token=admin["token"])
        assert res.status == 409

    def test_manager_reference_validated(self, api, admin, make_user):
        emp = make_user()
        res = api.call("users", "POST", "/", {"first_name": "X", "last_name": "Y", "email": "x@y.com",
                                              "job_title": "T", "role": "employee", "manager_id": emp["id"]},
                       token=admin["token"])
        assert res.status == 400 and "manager_id" in res.json["error"]["details"]


class TestUpdates:
    def test_everyone_edits_own_name_and_email_only(self, api, admin, make_user):
        for person in (make_user(), make_user(role="manager"), admin):
            res = api.call("users", "PUT", "/me", {"first_name": "New", "email": f"new{person['id']}@x.com"},
                           token=person["token"])
            assert res.status == 200 and res.json["first_name"] == "New"
            for field, value in (("job_title", "CEO"), ("salary_cents", 1), ("role", "admin"), ("manager_id", None)):
                assert api.call("users", "PUT", "/me", {field: value}, token=person["token"]).status == 403, field

    def test_nobody_changes_their_own_role_or_salary(self, api, admin):
        assert api.call("users", "PUT", f"/{admin['id']}", {"role": "manager"}, token=admin["token"]).status == 403
        assert api.call("users", "PUT", f"/{admin['id']}", {"salary_cents": 1}, token=admin["token"]).status == 403
        assert api.call("users", "PUT", f"/{admin['id']}", {"is_active": False}, token=admin["token"]).status == 409
        # unchanged values and other fields are fine
        assert api.call("users", "PUT", f"/{admin['id']}", {"role": "admin", "job_title": "Boss"},
                        token=admin["token"]).status == 200

    def test_admin_updates_other_users(self, api, admin, make_user):
        mgr = make_user(role="manager")
        emp = make_user()
        res = api.call("users", "PUT", f"/{emp['id']}", {"salary_cents": 9_900_000, "manager_id": mgr["id"]},
                       token=admin["token"])
        assert res.status == 200 and res.json["manager_name"] == mgr["full_name"]

    def test_cannot_demote_manager_with_reports(self, api, admin, make_user):
        mgr = make_user(role="manager")
        make_user(manager_id=mgr["id"])
        res = api.call("users", "PUT", f"/{mgr['id']}", {"role": "employee"}, token=admin["token"])
        assert res.status == 409 and res.json["error"]["details"]["direct_reports"] == 1

    def test_reporting_cycle_rejected(self, api, admin, make_user):
        top = make_user(role="manager")
        mid = make_user(role="manager", manager_id=top["id"])
        assert api.call("users", "PUT", f"/{top['id']}", {"manager_id": mid["id"]}, token=admin["token"]).status == 400

    def test_reset_password(self, api, admin, make_user):
        emp = make_user()
        res = api.call("users", "POST", f"/{emp['id']}/reset-password", token=admin["token"])
        assert res.status == 200 and len(res.json["temporary_password"]) == 6
        assert api.call("auth", "POST", "/login", {"email": emp["email"], "password": emp["password"]}).status == 401
        assert api.login(emp["email"], res.json["temporary_password"])
        assert api.call("users", "POST", f"/{emp['id']}/reset-password", token=emp["token"]).status == 403


class TestDirectory:
    def test_manager_sees_everyone_but_only_reports_salaries(self, api, make_user):
        mgr = make_user(role="manager")
        mine = make_user(manager_id=mgr["id"])
        other = make_user()
        res = api.call("users", "GET", "/", token=mgr["token"], query={"role": "employee"})
        by_id = {u["id"]: u for u in res.json["items"]}
        assert set(by_id) == {mine["id"], other["id"]}
        assert by_id[mine["id"]]["salary_cents"] == 10_400_000 and "salary_cents" not in by_id[other["id"]]
        assert "salary_cents" not in api.call("users", "GET", f"/{other['id']}", token=mgr["token"]).json

    def test_employee_sees_only_self(self, api, make_user):
        a, b = make_user(), make_user()
        assert api.call("users", "GET", "/", token=a["token"]).status == 403
        assert api.call("users", "GET", f"/{b['id']}", token=a["token"]).status == 404
        assert api.call("users", "GET", f"/{a['id']}", token=a["token"]).json["salary_cents"] == 10_400_000

    def test_search_filter_sort_paginate(self, api, admin, make_user):
        make_user(first_name="Zed", job_title="Designer")
        make_user(first_name="Amy", role="manager")
        make_user(first_name="Bob")
        get = lambda **q: api.call("users", "GET", "/", token=admin["token"], query=q).json  # noqa: E731
        assert [u["first_name"] for u in get(q="designer")["items"]] == ["Zed"]
        assert [u["first_name"] for u in get(role="manager")["items"]] == ["Amy"]
        page = get(role="employee", sort="-first_name", page_size=1, page=2)
        assert page["total"] == 2 and [u["first_name"] for u in page["items"]] == ["Bob"]
        assert api.call("users", "GET", "/", token=admin["token"], query={"sort": "password_hash"}).status == 400
        assert api.call("users", "GET", "/999", token=admin["token"]).status == 404
