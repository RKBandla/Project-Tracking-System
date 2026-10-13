"""Integration tests for the auth and users services."""

from shared import db

from .conftest import ADMIN_EMPLOYEE_ID, ADMIN_PASSWORD


class TestAuth:
    def test_login_returns_tokens_and_profile(self, api):
        res = api.call("auth", "POST", "/login", {"employee_id": "admin001", "password": ADMIN_PASSWORD})
        assert res.status == 200
        assert res.json["user"]["employee_id"] == ADMIN_EMPLOYEE_ID
        assert res.json["user"]["role"] == "admin"
        assert "password_hash" not in res.json["user"]
        assert res.json["access_token"] and res.json["refresh_token"]

    def test_wrong_password_and_unknown_user_look_identical(self, api):
        wrong = api.call("auth", "POST", "/login", {"employee_id": ADMIN_EMPLOYEE_ID, "password": "nope12"})
        unknown = api.call("auth", "POST", "/login", {"employee_id": "EMP9999", "password": "nope12"})
        assert wrong.status == unknown.status == 401
        assert wrong.json == unknown.json

    def test_login_validation(self, api):
        res = api.call("auth", "POST", "/login", {"employee_id": ""})
        assert res.status == 400
        assert set(res.json["error"]["details"]) == {"employee_id", "password"}

    def test_invalid_json(self, api):
        res = api.call("auth", "POST", "/login", raw_body="{not json")
        assert res.status == 400

    def test_refresh(self, api):
        login = api.call("auth", "POST", "/login", {"employee_id": ADMIN_EMPLOYEE_ID, "password": ADMIN_PASSWORD})
        res = api.call("auth", "POST", "/refresh", {"refresh_token": login.json["refresh_token"]})
        assert res.status == 200 and res.json["access_token"]
        # an access token cannot be used as a refresh token
        bad = api.call("auth", "POST", "/refresh", {"refresh_token": login.json["access_token"]})
        assert bad.status == 401

    def test_me_requires_token(self, api, admin):
        assert api.call("auth", "GET", "/me").status == 401
        assert api.call("auth", "GET", "/me", token="garbage").status == 401
        res = api.call("auth", "GET", "/me", token=admin["token"])
        assert res.status == 200 and res.json["id"] == admin["id"]

    def test_unknown_route_and_method(self, api, admin):
        assert api.call("auth", "GET", "/nope", token=admin["token"]).status == 404
        assert api.call("auth", "DELETE", "/me", token=admin["token"]).status == 405
        assert api.call("auth", "OPTIONS", "/login").status == 204

    def test_deactivated_user_is_locked_out(self, api, admin, make_user):
        emp = make_user()
        res = api.call("users", "PUT", f"/{emp['id']}", {"is_active": False}, token=admin["token"])
        assert res.status == 200
        assert api.call("auth", "GET", "/me", token=emp["token"]).status == 401
        login = api.call("auth", "POST", "/login", {"employee_id": emp["employee_id"], "password": emp["password"]})
        assert login.status == 401


class TestUserCreation:
    def test_admin_creates_user_with_generated_credentials(self, api, admin):
        res = api.call("users", "POST", "/", {
            "first_name": "Ada", "last_name": "Lovelace", "email": "ADA@Example.com",
            "job_title": "Engineer", "salary": 85000, "role": "employee",
        }, token=admin["token"])
        assert res.status == 201
        assert res.json["employee_id"] == "EMP0001"
        password = res.json["temporary_password"]
        assert len(password) == 6 and password.isalnum()
        user = res.json["user"]
        assert user["email"] == "ada@example.com" and user["salary"] == 85000
        assert "password_hash" not in user
        # only a hash is stored
        with db.cursor() as cur:
            cur.execute("SELECT password_hash FROM users WHERE id = %s", [user["id"]])
            stored = cur.fetchone()["password_hash"]
        assert password not in stored and stored.startswith("pbkdf2_sha256$")
        assert api.login("EMP0001", password)

    def test_admin_can_create_other_admins(self, api, make_user):
        other = make_user(role="admin")
        assert other["role"] == "admin"
        res = api.call("users", "POST", "/", {"first_name": "X", "last_name": "Y", "email": "x@y.com",
                                              "job_title": "Admin", "role": "admin"}, token=other["token"])
        assert res.status == 201

    def test_managers_and_employees_cannot_create_users(self, api, make_user):
        mgr = make_user(role="manager")
        emp = make_user(manager_id=mgr["id"])
        body = {"first_name": "X", "last_name": "Y", "email": "x@y.com", "job_title": "T", "role": "employee"}
        assert api.call("users", "POST", "/", body, token=mgr["token"]).status == 403
        assert api.call("users", "POST", "/", body, token=emp["token"]).status == 403

    def test_duplicate_email_conflicts(self, api, admin, make_user):
        make_user(email="dup@example.com")
        res = api.call("users", "POST", "/", {"first_name": "X", "last_name": "Y", "email": "DUP@example.com",
                                              "job_title": "T", "role": "employee"}, token=admin["token"])
        assert res.status == 409

    def test_validation(self, api, admin):
        res = api.call("users", "POST", "/", {"role": "boss", "email": "bad", "salary": -5}, token=admin["token"])
        assert res.status == 400
        assert {"first_name", "last_name", "email", "job_title", "salary", "role"} <= set(res.json["error"]["details"])

    def test_manager_must_be_manager_or_admin(self, api, admin, make_user):
        emp = make_user()
        res = api.call("users", "POST", "/", {"first_name": "X", "last_name": "Y", "email": "x@y.com",
                                              "job_title": "T", "role": "employee", "manager_id": emp["id"]},
                       token=admin["token"])
        assert res.status == 400 and "manager_id" in res.json["error"]["details"]


class TestProfileUpdates:
    def test_employee_updates_name_and_email(self, api, make_user):
        emp = make_user()
        res = api.call("users", "PUT", "/me", {"first_name": "New", "last_name": "Name", "email": "new@x.com"},
                       token=emp["token"])
        assert res.status == 200
        assert (res.json["first_name"], res.json["last_name"], res.json["email"]) == ("New", "Name", "new@x.com")

    def test_employee_cannot_update_anything_else(self, api, make_user):
        emp = make_user()
        for field, value in (("job_title", "CEO"), ("salary", 1e6), ("role", "admin"),
                             ("manager_id", None), ("is_active", True), ("employee_id", "X")):
            res = api.call("users", "PUT", "/me", {"first_name": "Ok", field: value}, token=emp["token"])
            assert res.status == 403, field
        assert api.call("users", "PUT", f"/{emp['id']}", {"first_name": "Z"}, token=emp["token"]).status == 403
        me = api.call("users", "GET", "/me", token=emp["token"]).json
        assert me["first_name"] == emp["first_name"] and me["job_title"] == "Engineer"

    def test_profile_validation(self, api, make_user):
        emp = make_user()
        assert api.call("users", "PUT", "/me", {"email": "not-an-email"}, token=emp["token"]).status == 400
        assert api.call("users", "PUT", "/me", {}, token=emp["token"]).status == 400
        assert api.call("users", "PUT", "/me", {"first_name": ""}, token=emp["token"]).status == 400

    def test_admin_updates_any_field(self, api, admin, make_user):
        mgr = make_user(role="manager")
        emp = make_user()
        res = api.call("users", "PUT", f"/{emp['id']}", {
            "job_title": "Senior Engineer", "salary": 99000, "manager_id": mgr["id"], "email": "e@x.com",
        }, token=admin["token"])
        assert res.status == 200
        assert res.json["job_title"] == "Senior Engineer" and res.json["manager_id"] == mgr["id"]
        assert res.json["manager_name"] == mgr["full_name"]

    def test_admin_cannot_demote_or_deactivate_self(self, api, admin):
        assert api.call("users", "PUT", f"/{admin['id']}", {"role": "employee"}, token=admin["token"]).status == 409
        assert api.call("users", "PUT", f"/{admin['id']}", {"is_active": False}, token=admin["token"]).status == 409

    def test_cannot_demote_manager_with_reports(self, api, admin, make_user):
        mgr = make_user(role="manager")
        make_user(manager_id=mgr["id"])
        res = api.call("users", "PUT", f"/{mgr['id']}", {"role": "employee"}, token=admin["token"])
        assert res.status == 409 and res.json["error"]["details"]["direct_reports"] == 1

    def test_reporting_cycle_rejected(self, api, admin, make_user):
        top = make_user(role="manager")
        mid = make_user(role="manager", manager_id=top["id"])
        res = api.call("users", "PUT", f"/{top['id']}", {"manager_id": mid["id"]}, token=admin["token"])
        assert res.status == 400
        res = api.call("users", "PUT", f"/{top['id']}", {"manager_id": top["id"]}, token=admin["token"])
        assert res.status == 400

    def test_reset_password(self, api, admin, make_user):
        emp = make_user()
        res = api.call("users", "POST", f"/{emp['id']}/reset-password", token=admin["token"])
        assert res.status == 200 and len(res.json["temporary_password"]) == 6
        old = api.call("auth", "POST", "/login", {"employee_id": emp["employee_id"], "password": emp["password"]})
        assert old.status == 401
        assert api.login(emp["employee_id"], res.json["temporary_password"])
        assert api.call("users", "POST", f"/{emp['id']}/reset-password", token=emp["token"]).status == 403


class TestUserVisibility:
    def test_manager_sees_only_direct_reports(self, api, make_user):
        mgr = make_user(role="manager")
        mine = make_user(manager_id=mgr["id"])
        make_user()
        res = api.call("users", "GET", "/", token=mgr["token"])
        assert res.status == 200
        assert [u["id"] for u in res.json["items"]] == [mine["id"]]
        assert res.json["items"][0]["salary"] == 50000
        assert api.call("users", "GET", f"/{mine['id']}", token=mgr["token"]).status == 200

    def test_employee_cannot_list_users_or_view_others(self, api, make_user):
        a, b = make_user(), make_user()
        assert api.call("users", "GET", "/", token=a["token"]).status == 403
        assert api.call("users", "GET", f"/{b['id']}", token=a["token"]).status == 404
        own = api.call("users", "GET", f"/{a['id']}", token=a["token"])
        assert own.status == 200 and own.json["salary"] == 50000

    def test_admin_search_filter_sort_paginate(self, api, admin, make_user):
        make_user(first_name="Zed", job_title="Designer")
        make_user(first_name="Amy", role="manager")
        make_user(first_name="Bob")
        res = api.call("users", "GET", "/", token=admin["token"], query={"q": "designer"})
        assert [u["first_name"] for u in res.json["items"]] == ["Zed"]
        res = api.call("users", "GET", "/", token=admin["token"], query={"role": "manager"})
        assert [u["first_name"] for u in res.json["items"]] == ["Amy"]
        res = api.call("users", "GET", "/", token=admin["token"],
                       query={"role": "employee", "sort": "-first_name", "page_size": 1, "page": 2})
        assert res.json["total"] == 2 and [u["first_name"] for u in res.json["items"]] == ["Bob"]
        res = api.call("users", "GET", "/", token=admin["token"], query={"page": 99})
        assert res.json["items"] == [] and res.json["total"] == 4
        assert api.call("users", "GET", "/", token=admin["token"], query={"sort": "password_hash"}).status == 400

    def test_get_missing_user(self, api, admin):
        assert api.call("users", "GET", "/999", token=admin["token"]).status == 404
