"""Integration tests for projects, the at-risk rule, project requests and the dashboard."""

from datetime import timedelta

import pytest

from shared import db

from .conftest import TODAY, monday


@pytest.fixture
def team(make_user, project_factory):
    """A manager with one direct report, a project they manage and an unrelated project."""
    mgr = make_user(role="manager")
    emp = make_user(manager_id=mgr["id"])
    project = project_factory(manager_id=mgr["id"], name="Apollo", budget_cents=100_000_00, status="active")
    other = project_factory(name="Gemini")
    return {"mgr": mgr, "emp": emp, "project": project, "other": other}


def approve_hours(cur_user_id: int, project_id: int, hours: float, work_date=None) -> None:
    """Insert approved hours directly (timesheet rules are tested elsewhere)."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO time_entries (user_id, project_id, work_date, hours, status) VALUES (%s, %s, %s, %s, 'approved')",
            [cur_user_id, project_id, work_date or TODAY, hours],
        )


class TestProjectCrud:
    def test_admin_creates_project(self, api, admin, make_user):
        mgr = make_user(role="manager")
        res = api.call("projects", "POST", "/", {
            "name": "Apollo", "description": "Moon", "status": "active", "start_date": "2026-01-01",
            "end_date": "2026-06-30", "manager_id": mgr["id"], "budget_cents": 500_000,
        }, token=admin["token"])
        assert res.status == 201
        p = res.json
        assert (p["code"], p["manager_name"], p["budget_cents"], p["is_archived"]) == \
            ("PRJ-0001", mgr["full_name"], 500_000, False)
        assert {"planned_cents", "consumed_cents", "at_risk", "risk_reasons"} <= set(p)

    def test_budget_must_be_whole_cents(self, api, admin):
        res = api.call("projects", "POST", "/", {"name": "X", "budget_cents": 12.5}, token=admin["token"])
        assert res.status == 400 and "budget_cents" in res.json["error"]["details"]

    def test_managers_request_instead_of_creating(self, api, team):
        res = api.call("projects", "POST", "/", {"name": "X"}, token=team["mgr"]["token"])
        assert res.status == 403 and "request" in res.json["error"]["message"]
        assert api.call("projects", "POST", "/", {"name": "X"}, token=team["emp"]["token"]).status == 403

    def test_manager_edits_only_description_and_status(self, api, team):
        t, pid = team["mgr"]["token"], team["project"]["id"]
        res = api.call("projects", "PUT", f"/{pid}", {"description": "Late", "status": "on_hold"}, token=t)
        assert res.status == 200 and res.json["status"] == "on_hold"
        for field, value in (("name", "X"), ("end_date", "2030-01-01"), ("budget_cents", 1), ("manager_id", None)):
            assert api.call("projects", "PUT", f"/{pid}", {field: value}, token=t).status == 403, field

    def test_admin_edits_all_fields_and_assigns_manager(self, api, admin, team, make_user):
        new_mgr = make_user(role="manager")
        res = api.call("projects", "PUT", f"/{team['project']['id']}",
                       {"name": "Apollo II", "manager_id": new_mgr["id"], "budget_cents": 1}, token=admin["token"])
        assert res.status == 200 and res.json["manager_id"] == new_mgr["id"]
        # the old manager now gets "not found", not "forbidden"
        assert api.call("projects", "GET", f"/{team['project']['id']}", token=team["mgr"]["token"]).status == 404

    def test_other_managers_project_is_not_found(self, api, team):
        assert api.call("projects", "GET", f"/{team['other']['id']}", token=team["mgr"]["token"]).status == 404
        assert api.call("projects", "PUT", f"/{team['other']['id']}", {"status": "active"},
                        token=team["mgr"]["token"]).status == 404

    def test_validation(self, api, admin):
        res = api.call("projects", "POST", "/", {"status": "done", "start_date": "2026-13-01"}, token=admin["token"])
        assert res.status == 400 and {"name", "status", "start_date"} <= set(res.json["error"]["details"])
        res = api.call("projects", "POST", "/", {"name": "X", "start_date": "2026-02-01", "end_date": "2026-01-01"},
                       token=admin["token"])
        assert res.status == 400

    def test_no_delete_route(self, api, admin, team):
        assert api.call("projects", "DELETE", f"/{team['project']['id']}", token=admin["token"]).status == 405


class TestVisibilityAndSearch:
    def test_each_role_sees_the_right_projects(self, api, admin, team, assign):
        names = lambda token: sorted(p["name"] for p in api.call("projects", "GET", "/", token=token).json["items"])  # noqa: E731
        assert names(admin["token"]) == ["Apollo", "Gemini"]
        assert names(team["mgr"]["token"]) == ["Apollo"]
        assert names(team["emp"]["token"]) == []
        assign(team["mgr"]["token"], team["project"], team["emp"], 10)
        assert names(team["emp"]["token"]) == ["Apollo"]

    def test_search_status_and_risk_filters(self, api, admin, project_factory):
        project_factory(name="Mercury", status="active")
        project_factory(name="Venus", status="on_hold", description="cloudy",
                        start_date=str(TODAY - timedelta(days=60)), end_date=str(TODAY - timedelta(days=1)))
        get = lambda **q: [p["name"] for p in api.call("projects", "GET", "/", token=admin["token"], query=q).json["items"]]  # noqa: E731
        assert get(q="cloud") == ["Venus"]
        assert get(q="PRJ-0001") == ["Mercury"]
        assert get(status="active") == ["Mercury"]
        assert get(at_risk="true") == ["Venus"]
        assert get(at_risk="false") == ["Mercury"]
        assert get(sort="-name") == ["Venus", "Mercury"]
        assert api.call("projects", "GET", "/", token=admin["token"], query={"status": "x"}).status == 400


class TestAtRisk:
    def test_on_track(self, api, admin, project_factory):
        p = project_factory(name="Fine", budget_cents=1_000_000)
        res = api.call("projects", "GET", f"/{p['id']}", token=admin["token"]).json
        assert res["at_risk"] is False and res["risk_reasons"] == []

    def test_past_end_date_and_not_complete(self, api, admin, project_factory):
        p = project_factory(name="Late", start_date=str(TODAY - timedelta(days=30)),
                            end_date=str(TODAY - timedelta(days=1)))
        res = api.call("projects", "GET", f"/{p['id']}", token=admin["token"]).json
        assert res["at_risk"] and "Past its end date" in res["risk_reasons"][0]
        done = api.call("projects", "PUT", f"/{p['id']}", {"status": "completed"}, token=admin["token"]).json
        assert done["at_risk"] is False

    def test_overdue_deliverable(self, api, admin, project_factory):
        p = project_factory(name="Slipping")
        api.call("deliverables", "POST", "/", {"project_id": p["id"], "title": "Spec",
                                               "due_date": str(TODAY - timedelta(days=2))}, token=admin["token"])
        res = api.call("projects", "GET", f"/{p['id']}", token=admin["token"]).json
        assert res["at_risk"] and res["risk_reasons"] == ["1 overdue deliverable"]

    def test_budget_burning_faster_than_schedule(self, api, admin, project_factory, make_user, assign):
        # Half the schedule elapsed (14 of 28 days); $1,000 budget
        p = project_factory(name="Burner", budget_cents=100_000,
                            start_date=str(TODAY - timedelta(days=14)), end_date=str(TODAY + timedelta(days=14)))
        emp = make_user()  # $50/h
        assert assign(admin["token"], p, emp, 10, start=TODAY - timedelta(days=14),
                      end=TODAY + timedelta(days=14)).status == 201
        approve_hours(emp["id"], p["id"], 12)  # $600 = 60% consumed, 50% elapsed -> within +15%
        assert api.call("projects", "GET", f"/{p['id']}", token=admin["token"]).json["at_risk"] is False
        approve_hours(emp["id"], p["id"], 2)  # $700 = 70% consumed -> over 50% + 15%
        res = api.call("projects", "GET", f"/{p['id']}", token=admin["token"]).json
        assert res["at_risk"] and "70% of budget consumed but only 50% of schedule elapsed" in res["risk_reasons"]


class TestArchiving:
    def test_archive_and_reactivate(self, api, admin, team):
        pid = team["project"]["id"]
        res = api.call("projects", "POST", f"/{pid}/archive", token=admin["token"])
        assert res.status == 200 and res.json["is_archived"] and res.json["at_risk"] is False
        listed = api.call("projects", "GET", "/", token=admin["token"]).json["items"]
        assert pid not in [p["id"] for p in listed]
        archived = api.call("projects", "GET", "/", token=admin["token"], query={"archived": "true"}).json["items"]
        assert [p["id"] for p in archived] == [pid]
        assert api.call("projects", "POST", f"/{pid}/archive", token=admin["token"]).status == 409
        assert api.call("projects", "PUT", f"/{pid}", {"name": "X"}, token=admin["token"]).status == 409
        res = api.call("projects", "POST", f"/{pid}/reactivate", token=admin["token"])
        assert res.status == 200 and not res.json["is_archived"]
        assert api.call("projects", "POST", f"/{pid}/reactivate", token=admin["token"]).status == 409

    def test_only_admin_archives(self, api, team):
        pid = team["project"]["id"]
        assert api.call("projects", "POST", f"/{pid}/archive", token=team["mgr"]["token"]).status == 403
        assert api.call("projects", "POST", f"/{pid}/reactivate", token=team["mgr"]["token"]).status == 403

    def test_missing_project(self, api, admin):
        assert api.call("projects", "POST", "/999/archive", token=admin["token"]).status == 404
        assert api.call("projects", "POST", "/999/reactivate", token=admin["token"]).status == 404

    def test_reactivation_rechecks_weekly_capacity(self, api, admin, team, project_factory, assign):
        emp, project = team["emp"], team["project"]
        assert assign(admin["token"], project, emp, 30).status == 201
        api.call("projects", "POST", f"/{project['id']}/archive", token=admin["token"])
        other = project_factory(name="Other")
        assert assign(admin["token"], other, emp, 20).status == 201
        res = api.call("projects", "POST", f"/{project['id']}/reactivate", token=admin["token"])
        assert res.status == 409
        names = {p["code"] for p in res.json["error"]["details"]["conflicting_projects"]}
        assert names == {project["code"], other["code"]}
        # still archived after the refused reactivation
        assert api.call("projects", "GET", f"/{project['id']}", token=admin["token"]).json["is_archived"]


class TestSummaryAndDashboard:
    def test_summary(self, api, admin, team, assign):
        pid, emp = team["project"]["id"], team["emp"]
        assign(admin["token"], team["project"], emp, 16)
        for title, status in (("A", "done"), ("B", "todo"), ("C", "blocked")):
            api.call("deliverables", "POST", "/", {"project_id": pid, "title": title, "status": status,
                                                   "due_date": str(TODAY - timedelta(days=1))}, token=admin["token"])
        approve_hours(emp["id"], pid, 10)
        res = api.call("projects", "GET", f"/{pid}/summary", token=team["mgr"]["token"])
        assert res.status == 200
        d = res.json["deliverables"]
        assert (d["total"], d["done"], d["blocked"], d["overdue"], d["completion_pct"]) == (3, 1, 1, 2, 33)
        assert res.json["team"]["weekly_hours"] == 16 and res.json["team"]["size"] == 1
        b = res.json["budget"]
        assert b["planned_cents"] == 16 * 4 * 5000  # 16 h/week x 4 weeks x $50/h
        assert b["consumed_cents"] == 10 * 5000 and b["remaining_cents"] == 100_000_00 - 50_000
        assert res.json["at_risk"] and "2 overdue deliverables" in res.json["risk_reasons"]

    def test_milestones_on_dashboard_and_in_risk_reasons(self, api, admin, project_factory):
        p, t = project_factory(name="Launch"), admin["token"]
        for title, days in (("Beta", -2), ("Go-live", 20), ("Far away", 120)):
            res = api.call("deliverables", "POST", "/", {"project_id": p["id"], "title": title, "is_milestone": True,
                                                         "due_date": str(TODAY + timedelta(days=days))}, token=t)
            assert res.status == 201
        api.call("deliverables", "POST", "/", {"project_id": p["id"], "title": "Spec",
                                               "due_date": str(TODAY + timedelta(days=5))}, token=t)
        d = api.call("projects", "GET", "/dashboard", token=t).json
        assert [(m["title"], m["is_missed"]) for m in d["upcoming_milestones"]] == [("Beta", True), ("Go-live", False)]
        res = api.call("projects", "GET", f"/{p['id']}", token=t).json
        assert res["at_risk"] and res["risk_reasons"] == ["1 overdue deliverable (1 missed milestone)"]
        audit = api.call("activity", "GET", "/audit", token=t, query={"q": "milestone"}).json
        assert audit["total"] == 3

    def test_dashboards(self, api, admin, team, assign, project_factory):
        mgr, emp = team["mgr"], team["emp"]
        assign(mgr["token"], team["project"], emp, 40)
        late = project_factory(name="Late", manager_id=mgr["id"], end_date=str(TODAY - timedelta(days=1)),
                               start_date=str(TODAY - timedelta(days=10)))
        api.call("deliverables", "POST", "/", {"project_id": team["project"]["id"], "title": "Soon",
                                               "assignee_id": emp["id"], "due_date": str(TODAY + timedelta(days=3))},
                 token=mgr["token"])
        api.call("project-requests", "POST", "/", {"name": "New idea"}, token=mgr["token"])

        a = api.call("projects", "GET", "/dashboard", token=admin["token"]).json
        assert a["projects_total"] == 3 and a["pending_requests"] == 1
        assert [p["name"] for p in a["at_risk_projects"]] == ["Late"]
        assert "Past its end date" in a["at_risk_projects"][0]["risk_reasons"][0]
        assert [p["id"] for p in a["fully_booked_people"]] == [emp["id"]]
        assert a["unread_notifications"] == 0

        m = api.call("projects", "GET", "/dashboard", token=mgr["token"]).json
        assert m["projects_total"] == 2 and m["at_risk_count"] == 1 and m["hours_to_approve"] == 0

        e = api.call("projects", "GET", "/dashboard", token=emp["token"]).json
        assert e["my_week_hours"] == 40 and [d["title"] for d in e["upcoming_deliverables"]] == ["Soon"]
        assert late["id"] not in [p["id"] for p in e["at_risk_projects"]]


class TestProjectRequests:
    def test_request_approval_flow(self, api, admin, make_user):
        mgr = make_user(role="manager")
        res = api.call("project-requests", "POST", "/", {
            "name": "Zeus", "justification": "Growth", "proposed_start_date": str(monday()),
            "proposed_end_date": str(monday(10)), "proposed_budget_cents": 2_500_000,
        }, token=mgr["token"])
        assert res.status == 201 and res.json["status"] == "pending"
        rid = res.json["id"]
        assert api.call("project-requests", "POST", f"/{rid}/approve", token=mgr["token"]).status == 403
        res = api.call("project-requests", "POST", f"/{rid}/approve", {"review_note": "Go"}, token=admin["token"])
        assert res.status == 200 and res.json["request"]["status"] == "approved"
        project = res.json["project"]
        assert project["manager_id"] == mgr["id"] and project["budget_cents"] == 2_500_000
        assert api.call("projects", "GET", f"/{project['id']}", token=mgr["token"]).status == 200
        assert api.call("project-requests", "POST", f"/{rid}/approve", token=admin["token"]).status == 409

    def test_reject_edit_withdraw(self, api, admin, make_user):
        mgr = make_user(role="manager")
        r1 = api.call("project-requests", "POST", "/", {"name": "Hermes"}, token=mgr["token"]).json["id"]
        assert api.call("project-requests", "POST", f"/{r1}/reject", {}, token=admin["token"]).status == 400
        res = api.call("project-requests", "POST", f"/{r1}/reject", {"review_note": "No"}, token=admin["token"])
        assert res.json["status"] == "rejected"
        r2 = api.call("project-requests", "POST", "/", {"name": "Ares"}, token=mgr["token"]).json["id"]
        assert api.call("project-requests", "PUT", f"/{r2}", {"proposed_budget_cents": 10},
                        token=mgr["token"]).json["proposed_budget_cents"] == 10
        assert api.call("project-requests", "PUT", f"/{r2}", {"name": "X"}, token=admin["token"]).status == 403
        assert api.call("project-requests", "POST", f"/{r2}/withdraw", token=mgr["token"]).json["status"] == "withdrawn"
        assert api.call("project-requests", "PUT", f"/{r2}", {"name": "X"}, token=mgr["token"]).status == 409

    def test_visibility(self, api, admin, make_user):
        m1, m2 = make_user(role="manager"), make_user(role="manager")
        emp = make_user(manager_id=m1["id"])
        rid = api.call("project-requests", "POST", "/", {"name": "Mine"}, token=m1["token"]).json["id"]
        api.call("project-requests", "POST", "/", {"name": "Theirs"}, token=m2["token"])
        assert api.call("project-requests", "POST", "/", {"name": "X"}, token=emp["token"]).status == 403
        assert api.call("project-requests", "GET", "/", token=emp["token"]).status == 403
        assert [r["name"] for r in api.call("project-requests", "GET", "/", token=m1["token"]).json["items"]] == ["Mine"]
        assert api.call("project-requests", "GET", f"/{rid}", token=m2["token"]).status == 404
        assert api.call("project-requests", "GET", "/", token=admin["token"], query={"status": "pending"}).json["total"] == 2

    def test_cannot_approve_for_deactivated_requester(self, api, admin, make_user):
        mgr = make_user(role="manager")
        rid = api.call("project-requests", "POST", "/", {"name": "Orphan"}, token=mgr["token"]).json["id"]
        api.call("users", "PUT", f"/{mgr['id']}", {"is_active": False}, token=admin["token"])
        assert api.call("project-requests", "POST", f"/{rid}/approve", token=admin["token"]).status == 409
