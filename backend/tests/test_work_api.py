"""Integration tests for assignments (40-hour rule), deliverables and budgets."""

import pytest


@pytest.fixture
def team(make_user, project_factory):
    """A manager, two direct reports, an outsider and two projects managed by the manager."""
    mgr = make_user(role="manager")
    emp = make_user(manager_id=mgr["id"])
    emp2 = make_user(manager_id=mgr["id"])
    outsider = make_user()
    p1 = project_factory(manager_id=mgr["id"], name="Apollo")
    p2 = project_factory(manager_id=mgr["id"], name="Gemini")
    return {"mgr": mgr, "emp": emp, "emp2": emp2, "outsider": outsider, "p1": p1, "p2": p2}


def assign(api, token, project, user, hours, **extra):
    """Create an assignment and return the response."""
    return api.call("assignments", "POST", "/", {"project_id": project["id"], "user_id": user["id"],
                                                 "hours_per_week": hours, **extra}, token=token)


class TestAssignments:
    def test_manager_assigns_direct_report_to_multiple_projects(self, api, team):
        t = team["mgr"]["token"]
        res = assign(api, t, team["p1"], team["emp"], 24, project_role="Developer")
        assert res.status == 201
        assert res.json["project_role"] == "Developer" and res.json["full_name"] == team["emp"]["full_name"]
        assert assign(api, t, team["p2"], team["emp"], 16).status == 201
        workload = api.call("users", "GET", f"/{team['emp']['id']}/workload", token=team["emp"]["token"]).json
        assert (workload["allocated_hours"], workload["remaining_hours"]) == (40, 0)
        assert len(workload["assignments"]) == 2

    def test_40_hour_weekly_limit(self, api, team):
        t = team["mgr"]["token"]
        assert assign(api, t, team["p1"], team["emp"], 30).status == 201
        res = assign(api, t, team["p2"], team["emp"], 15)
        assert res.status == 409
        details = res.json["error"]["details"]
        assert (details["allocated_hours"], details["remaining_hours"]) == (30, 10)
        assert assign(api, t, team["p2"], team["emp"], 10).status == 201

    def test_hours_must_be_between_1_and_40(self, api, team):
        t = team["mgr"]["token"]
        assert assign(api, t, team["p1"], team["emp"], 0).status == 400
        assert assign(api, t, team["p1"], team["emp"], 41).status == 400

    def test_update_hours_respects_limit(self, api, team):
        t = team["mgr"]["token"]
        a1 = assign(api, t, team["p1"], team["emp"], 20).json
        assign(api, t, team["p2"], team["emp"], 20)
        assert api.call("assignments", "PUT", f"/{a1['id']}", {"hours_per_week": 21}, token=t).status == 409
        res = api.call("assignments", "PUT", f"/{a1['id']}", {"hours_per_week": 15, "project_role": "Lead"}, token=t)
        assert res.status == 200 and res.json["hours_per_week"] == 15 and res.json["project_role"] == "Lead"
        assert api.call("assignments", "PUT", f"/{a1['id']}", {}, token=t).status == 400
        assert api.call("assignments", "PUT", f"/{a1['id']}", {"hours_per_week": None}, token=t).status == 400

    def test_duplicate_assignment(self, api, team):
        t = team["mgr"]["token"]
        assign(api, t, team["p1"], team["emp"], 5)
        assert assign(api, t, team["p1"], team["emp"], 5).status == 409

    def test_manager_can_only_assign_direct_reports(self, api, team):
        res = assign(api, team["mgr"]["token"], team["p1"], team["outsider"], 5)
        assert res.status == 403

    def test_manager_can_only_assign_to_own_projects(self, api, team, project_factory):
        foreign = project_factory(name="Foreign")
        assert assign(api, team["mgr"]["token"], foreign, team["emp"], 5).status == 404

    def test_admin_assigns_anyone(self, api, admin, team):
        assert assign(api, admin["token"], team["p1"], team["outsider"], 5).status == 201

    def test_cannot_assign_admin_or_inactive(self, api, admin, team, make_user):
        other_admin = make_user(role="admin")
        assert assign(api, admin["token"], team["p1"], other_admin, 5).status == 400
        api.call("users", "PUT", f"/{team['outsider']['id']}", {"is_active": False}, token=admin["token"])
        assert assign(api, admin["token"], team["p1"], team["outsider"], 5).status == 400
        assert assign(api, admin["token"], team["p1"], {"id": 999}, 5).status == 400

    def test_employee_cannot_assign_and_sees_only_own(self, api, team):
        assign(api, team["mgr"]["token"], team["p1"], team["emp"], 5)
        assign(api, team["mgr"]["token"], team["p1"], team["emp2"], 5)
        assert assign(api, team["emp"]["token"], team["p1"], team["emp"], 5).status == 403
        own = api.call("assignments", "GET", "/", token=team["emp"]["token"]).json["items"]
        assert [a["user_id"] for a in own] == [team["emp"]["id"]]

    def test_list_filters(self, api, team):
        t = team["mgr"]["token"]
        assign(api, t, team["p1"], team["emp"], 5)
        assign(api, t, team["p2"], team["emp2"], 5)
        res = api.call("assignments", "GET", "/", token=t, query={"project_id": team["p2"]["id"]})
        assert [a["user_id"] for a in res.json["items"]] == [team["emp2"]["id"]]
        res = api.call("assignments", "GET", "/", token=t, query={"q": "gemini"})
        assert res.json["total"] == 1

    def test_unassign_clears_open_deliverables(self, api, team):
        t = team["mgr"]["token"]
        a = assign(api, t, team["p1"], team["emp"], 5).json
        d = api.call("deliverables", "POST", "/", {"project_id": team["p1"]["id"], "title": "Spec",
                                                   "assignee_id": team["emp"]["id"]}, token=t).json
        assert api.call("assignments", "DELETE", f"/{a['id']}", token=t).status == 204
        assert api.call("deliverables", "GET", f"/{d['id']}", token=t).json["assignee_id"] is None
        assert api.call("assignments", "GET", f"/{a['id']}", token=t).status == 404
        # employee no longer sees the project
        assert api.call("projects", "GET", f"/{team['p1']['id']}", token=team["emp"]["token"]).status == 404


class TestDeliverables:
    def test_crud(self, api, team):
        t, pid = team["mgr"]["token"], team["p1"]["id"]
        assign(api, t, team["p1"], team["emp"], 5)
        res = api.call("deliverables", "POST", "/", {"project_id": pid, "title": "Design", "due_date": "2030-01-01",
                                                     "assignee_id": team["emp"]["id"]}, token=t)
        assert res.status == 201
        d = res.json
        assert (d["status"], d["progress_pct"], d["assignee_name"]) == ("todo", 0, team["emp"]["full_name"])
        res = api.call("deliverables", "PUT", f"/{d['id']}", {"status": "done"}, token=t)
        assert res.status == 200 and res.json["progress_pct"] == 100
        assert api.call("deliverables", "DELETE", f"/{d['id']}", token=t).status == 204
        assert api.call("deliverables", "GET", f"/{d['id']}", token=t).status == 404

    def test_assignee_must_be_on_project(self, api, team):
        res = api.call("deliverables", "POST", "/", {"project_id": team["p1"]["id"], "title": "X",
                                                     "assignee_id": team["emp2"]["id"]}, token=team["mgr"]["token"])
        assert res.status == 400 and "assignee_id" in res.json["error"]["details"]
        # the project manager can always own a deliverable
        res = api.call("deliverables", "POST", "/", {"project_id": team["p1"]["id"], "title": "X",
                                                     "assignee_id": team["mgr"]["id"]}, token=team["mgr"]["token"])
        assert res.status == 201

    def test_employee_reads_but_cannot_change(self, api, team):
        t = team["mgr"]["token"]
        assign(api, t, team["p1"], team["emp"], 5)
        d = api.call("deliverables", "POST", "/", {"project_id": team["p1"]["id"], "title": "Spec",
                                                   "assignee_id": team["emp"]["id"]}, token=t).json
        api.call("deliverables", "POST", "/", {"project_id": team["p2"]["id"], "title": "Hidden"}, token=t)
        et = team["emp"]["token"]
        listed = api.call("deliverables", "GET", "/", token=et).json["items"]
        assert [x["title"] for x in listed] == ["Spec"]
        assert api.call("deliverables", "PUT", f"/{d['id']}", {"status": "done"}, token=et).status == 403
        assert api.call("deliverables", "DELETE", f"/{d['id']}", token=et).status == 403
        assert api.call("deliverables", "POST", "/", {"project_id": team["p1"]["id"], "title": "X"},
                        token=et).status == 403

    def test_filters(self, api, team):
        t, pid = team["mgr"]["token"], team["p1"]["id"]
        for title, status, due in (("Late", "todo", "2000-01-01"), ("Done", "done", "2000-01-01"),
                                   ("Future", "in_progress", "2099-01-01")):
            api.call("deliverables", "POST", "/", {"project_id": pid, "title": title, "status": status,
                                                   "due_date": due}, token=t)
        get = lambda **q: [d["title"] for d in api.call("deliverables", "GET", "/", token=t, query=q).json["items"]]
        assert get(overdue="true") == ["Late"]
        assert get(status="done") == ["Done"]
        assert get(q="fut") == ["Future"]
        assert get(due_after="2050-01-01") == ["Future"]
        assert get(due_before="2001-01-01", sort="title") == ["Done", "Late"]

    def test_validation(self, api, team):
        res = api.call("deliverables", "POST", "/", {"project_id": team["p1"]["id"], "title": "",
                                                     "progress_pct": 101, "status": "nope"}, token=team["mgr"]["token"])
        assert res.status == 400
        assert {"title", "progress_pct", "status"} <= set(res.json["error"]["details"])
        res = api.call("deliverables", "POST", "/", {"project_id": 999, "title": "X"}, token=team["mgr"]["token"])
        assert res.status == 404


class TestBudgets:
    def test_crud_and_totals(self, api, team):
        t, pid = team["mgr"]["token"], team["p1"]["id"]
        res = api.call("budgets", "POST", "/", {"project_id": pid, "category": "labor", "description": "Devs",
                                                "planned_amount": 1000, "actual_amount": 400.5}, token=t)
        assert res.status == 201 and res.json["actual_amount"] == 400.5 and res.json["entry_date"]
        item = res.json
        api.call("budgets", "POST", "/", {"project_id": pid, "category": "software", "description": "Licences",
                                          "planned_amount": 200}, token=t)
        listed = api.call("budgets", "GET", "/", token=t, query={"project_id": pid}).json
        assert listed["total"] == 2 and listed["totals"] == {"planned": 1200, "actual": 400.5}
        filtered = api.call("budgets", "GET", "/", token=t, query={"category": "software"}).json
        assert [i["description"] for i in filtered["items"]] == ["Licences"]
        res = api.call("budgets", "PUT", f"/{item['id']}", {"actual_amount": 900}, token=t)
        assert res.status == 200 and res.json["actual_amount"] == 900
        assert api.call("budgets", "PUT", f"/{item['id']}", {"category": None}, token=t).status == 400
        assert api.call("budgets", "DELETE", f"/{item['id']}", token=t).status == 204

    def test_employees_have_no_budget_access(self, api, team):
        et = team["emp"]["token"]
        assert api.call("budgets", "GET", "/", token=et).status == 403
        assert api.call("budgets", "POST", "/", {"project_id": team["p1"]["id"], "category": "labor",
                                                 "description": "X"}, token=et).status == 403

    def test_manager_limited_to_own_projects(self, api, admin, team, project_factory):
        foreign = project_factory(name="Foreign")
        res = api.call("budgets", "POST", "/", {"project_id": foreign["id"], "category": "labor",
                                                "description": "X"}, token=team["mgr"]["token"])
        assert res.status == 404
        item = api.call("budgets", "POST", "/", {"project_id": foreign["id"], "category": "labor",
                                                 "description": "X"}, token=admin["token"]).json
        assert api.call("budgets", "GET", f"/{item['id']}", token=team["mgr"]["token"]).status == 404

    def test_validation(self, api, team):
        res = api.call("budgets", "POST", "/", {"project_id": team["p1"]["id"], "category": "food",
                                                "planned_amount": -1}, token=team["mgr"]["token"])
        assert res.status == 400
        assert {"category", "description", "planned_amount"} <= set(res.json["error"]["details"])
