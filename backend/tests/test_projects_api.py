"""Integration tests for projects, project requests and archiving."""

import pytest


@pytest.fixture
def team(make_user, project_factory):
    """A manager with one direct report, a project they manage and an unrelated project."""
    mgr = make_user(role="manager")
    emp = make_user(manager_id=mgr["id"])
    project = project_factory(manager_id=mgr["id"], name="Apollo", budget_total=1000, status="active")
    other = project_factory(name="Gemini")
    return {"mgr": mgr, "emp": emp, "project": project, "other": other}


class TestProjectCrud:
    def test_admin_creates_project_with_generated_code(self, api, admin, make_user):
        mgr = make_user(role="manager")
        res = api.call("projects", "POST", "/", {
            "name": "Apollo", "description": "Moon", "status": "active", "health": "amber",
            "start_date": "2026-01-01", "end_date": "2026-06-30", "manager_id": mgr["id"], "budget_total": 5000,
        }, token=admin["token"])
        assert res.status == 201
        assert res.json["code"] == "PRJ-0001" and res.json["manager_name"] == mgr["full_name"]
        assert res.json["is_archived"] is False and res.json["budget_total"] == 5000

    def test_defaults(self, api, admin):
        res = api.call("projects", "POST", "/", {"name": "Minimal"}, token=admin["token"])
        assert res.status == 201
        assert (res.json["status"], res.json["health"], res.json["budget_total"]) == ("planned", "green", 0)

    def test_manager_and_employee_cannot_create(self, api, team):
        res = api.call("projects", "POST", "/", {"name": "X"}, token=team["mgr"]["token"])
        assert res.status == 403 and "request" in res.json["error"]["message"]
        assert api.call("projects", "POST", "/", {"name": "X"}, token=team["emp"]["token"]).status == 403

    def test_validation(self, api, admin, make_user):
        emp = make_user()
        res = api.call("projects", "POST", "/", {"status": "done", "budget_total": -1,
                                                 "start_date": "2026-13-01"}, token=admin["token"])
        assert res.status == 400
        assert {"name", "status", "budget_total", "start_date"} <= set(res.json["error"]["details"])
        res = api.call("projects", "POST", "/", {"name": "X", "start_date": "2026-02-01",
                                                 "end_date": "2026-01-01"}, token=admin["token"])
        assert res.status == 400
        res = api.call("projects", "POST", "/", {"name": "X", "manager_id": emp["id"]}, token=admin["token"])
        assert res.status == 400

    def test_manager_edits_own_project_but_not_manager_field(self, api, team, make_user):
        mgr, project = team["mgr"], team["project"]
        res = api.call("projects", "PUT", f"/{project['id']}", {"health": "red", "description": "Late"},
                       token=mgr["token"])
        assert res.status == 200 and res.json["health"] == "red"
        other_mgr = make_user(role="manager")
        res = api.call("projects", "PUT", f"/{project['id']}", {"manager_id": other_mgr["id"]}, token=mgr["token"])
        assert res.status == 403
        assert api.call("projects", "PUT", f"/{team['other']['id']}", {"name": "X"},
                        token=mgr["token"]).status == 404

    def test_admin_assigns_project_manager(self, api, admin, team, make_user):
        new_mgr = make_user(role="manager")
        res = api.call("projects", "PUT", f"/{team['project']['id']}", {"manager_id": new_mgr["id"]},
                       token=admin["token"])
        assert res.status == 200 and res.json["manager_id"] == new_mgr["id"]
        # old manager loses access
        assert api.call("projects", "GET", f"/{team['project']['id']}", token=team["mgr"]["token"]).status == 404

    def test_update_validation(self, api, admin, team):
        pid = team["project"]["id"]
        assert api.call("projects", "PUT", f"/{pid}", {}, token=admin["token"]).status == 400
        assert api.call("projects", "PUT", f"/{pid}", {"name": None}, token=admin["token"]).status == 400
        assert api.call("projects", "PUT", f"/{pid}", {"end_date": "2000-01-01", "start_date": "2001-01-01"},
                        token=admin["token"]).status == 400

    def test_employee_cannot_edit(self, api, team):
        res = api.call("projects", "PUT", f"/{team['project']['id']}", {"name": "X"}, token=team["emp"]["token"])
        assert res.status == 404  # not assigned, so not even visible

    def test_no_delete_route(self, api, admin, team):
        assert api.call("projects", "DELETE", f"/{team['project']['id']}", token=admin["token"]).status == 405


class TestVisibility:
    def test_each_role_sees_the_right_projects(self, api, admin, team):
        names = lambda token: sorted(p["name"] for p in api.call("projects", "GET", "/", token=token).json["items"])
        assert names(admin["token"]) == ["Apollo", "Gemini"]
        assert names(team["mgr"]["token"]) == ["Apollo"]
        assert names(team["emp"]["token"]) == []
        api.call("assignments", "POST", "/", {"project_id": team["project"]["id"], "user_id": team["emp"]["id"],
                                              "hours_per_week": 10}, token=team["mgr"]["token"])
        assert names(team["emp"]["token"]) == ["Apollo"]

    def test_employee_does_not_see_budget(self, api, team):
        api.call("assignments", "POST", "/", {"project_id": team["project"]["id"], "user_id": team["emp"]["id"],
                                              "hours_per_week": 10}, token=team["mgr"]["token"])
        res = api.call("projects", "GET", f"/{team['project']['id']}", token=team["emp"]["token"])
        assert res.status == 200 and "budget_total" not in res.json
        listed = api.call("projects", "GET", "/", token=team["emp"]["token"]).json["items"][0]
        assert "budget_total" not in listed
        summary = api.call("projects", "GET", f"/{team['project']['id']}/summary", token=team["emp"]["token"])
        assert summary.status == 200 and "budget" not in summary.json

    def test_search_and_filters(self, api, admin, project_factory):
        project_factory(name="Mercury", status="active", health="red", start_date="2026-03-01")
        project_factory(name="Venus", status="on_hold", description="cloudy planet")
        get = lambda **q: [p["name"] for p in api.call("projects", "GET", "/", token=admin["token"],
                                                         query=q).json["items"]]
        assert get(q="cloud") == ["Venus"]
        assert get(q="PRJ-0001") == ["Mercury"]
        assert get(status="active") == ["Mercury"]
        assert get(health="red") == ["Mercury"]
        assert get(start_from="2026-02-01") == ["Mercury"]
        assert get(sort="-name") == ["Venus", "Mercury"]
        assert api.call("projects", "GET", "/", token=admin["token"], query={"status": "x"}).status == 400


class TestArchiving:
    def test_archive_and_reactivate(self, api, admin, team):
        pid = team["project"]["id"]
        res = api.call("projects", "POST", f"/{pid}/archive", token=admin["token"])
        assert res.status == 200 and res.json["is_archived"] and res.json["archived_at"]
        # hidden by default, visible with the archived filter, record kept
        listed = api.call("projects", "GET", "/", token=admin["token"]).json["items"]
        assert pid not in [p["id"] for p in listed]
        archived = api.call("projects", "GET", "/", token=admin["token"], query={"archived": "true"}).json["items"]
        assert [p["id"] for p in archived] == [pid]
        assert api.call("projects", "GET", f"/{pid}", token=admin["token"]).status == 200
        assert api.call("projects", "POST", f"/{pid}/archive", token=admin["token"]).status == 409

        res = api.call("projects", "POST", f"/{pid}/reactivate", token=admin["token"])
        assert res.status == 200 and not res.json["is_archived"] and res.json["archived_at"] is None
        assert api.call("projects", "POST", f"/{pid}/reactivate", token=admin["token"]).status == 409

    def test_archived_project_is_read_only(self, api, admin, team):
        pid = team["project"]["id"]
        api.call("projects", "POST", f"/{pid}/archive", token=admin["token"])
        assert api.call("projects", "PUT", f"/{pid}", {"name": "X"}, token=admin["token"]).status == 409
        res = api.call("assignments", "POST", "/", {"project_id": pid, "user_id": team["emp"]["id"],
                                                    "hours_per_week": 5}, token=admin["token"])
        assert res.status == 409
        res = api.call("deliverables", "POST", "/", {"project_id": pid, "title": "D"}, token=admin["token"])
        assert res.status == 409

    def test_only_admin_archives(self, api, team):
        pid = team["project"]["id"]
        assert api.call("projects", "POST", f"/{pid}/archive", token=team["mgr"]["token"]).status == 403
        assert api.call("projects", "POST", f"/{pid}/reactivate", token=team["mgr"]["token"]).status == 403
        assert api.call("projects", "POST", "/999/archive", token=team["mgr"]["token"]).status == 403

    def test_archive_missing_project(self, api, admin):
        assert api.call("projects", "POST", "/999/archive", token=admin["token"]).status == 404
        assert api.call("projects", "POST", "/999/reactivate", token=admin["token"]).status == 404

    def test_archived_hours_free_capacity_and_reactivation_checks_it(self, api, admin, team, project_factory):
        emp, pid = team["emp"], team["project"]["id"]
        assert api.call("assignments", "POST", "/", {"project_id": pid, "user_id": emp["id"], "hours_per_week": 30},
                        token=admin["token"]).status == 201
        api.call("projects", "POST", f"/{pid}/archive", token=admin["token"])
        other = project_factory(name="Other")
        assert api.call("assignments", "POST", "/", {"project_id": other["id"], "user_id": emp["id"],
                                                     "hours_per_week": 20}, token=admin["token"]).status == 201
        res = api.call("projects", "POST", f"/{pid}/reactivate", token=admin["token"])
        assert res.status == 409
        assert res.json["error"]["details"]["over_allocated"][0]["user_id"] == emp["id"]


class TestSummaryAndDashboard:
    def test_summary(self, api, admin, team):
        pid, emp = team["project"]["id"], team["emp"]
        api.call("assignments", "POST", "/", {"project_id": pid, "user_id": emp["id"], "hours_per_week": 16},
                 token=admin["token"])
        for title, status in (("A", "done"), ("B", "todo"), ("C", "blocked")):
            api.call("deliverables", "POST", "/", {"project_id": pid, "title": title, "status": status,
                                                   "due_date": "2000-01-01"}, token=admin["token"])
        api.call("budgets", "POST", "/", {"project_id": pid, "category": "labor", "description": "Dev",
                                          "planned_amount": 800, "actual_amount": 250}, token=admin["token"])
        res = api.call("projects", "GET", f"/{pid}/summary", token=team["mgr"]["token"])
        assert res.status == 200
        d = res.json["deliverables"]
        assert (d["total"], d["done"], d["blocked"], d["overdue"], d["completion_pct"]) == (3, 1, 1, 2, 33)
        assert res.json["team"]["total_hours"] == 16 and res.json["team"]["size"] == 1
        b = res.json["budget"]
        assert (b["planned"], b["actual"], b["remaining"], b["burn_pct"]) == (800, 250, 750, 25.0)

    def test_dashboards(self, api, admin, team):
        pid, emp, mgr = team["project"]["id"], team["emp"], team["mgr"]
        api.call("assignments", "POST", "/", {"project_id": pid, "user_id": emp["id"], "hours_per_week": 40},
                 token=mgr["token"])
        api.call("deliverables", "POST", "/", {"project_id": pid, "title": "Soon", "assignee_id": emp["id"],
                                               "due_date": "2000-01-01"}, token=mgr["token"])
        api.call("project-requests", "POST", "/", {"name": "New idea"}, token=mgr["token"])

        a = api.call("projects", "GET", "/dashboard", token=admin["token"]).json
        assert a["projects_total"] == 2 and a["pending_requests"] == 1 and a["archived_projects"] == 0
        assert a["capacity"]["fully_allocated"] == 1 and a["overdue_deliverables"] == 1

        m = api.call("projects", "GET", "/dashboard", token=mgr["token"]).json
        assert m["projects_total"] == 1 and m["pending_requests"] == 1
        assert [p["id"] for p in m["capacity"]["team"]] == [emp["id"]]

        e = api.call("projects", "GET", "/dashboard", token=emp["token"]).json
        assert e["my_hours"] == {"allocated": 40, "remaining": 0}
        assert [d["title"] for d in e["upcoming_deliverables"]] == ["Soon"]
        assert "budget" not in e and "capacity" not in e


class TestProjectRequests:
    def test_request_approval_flow(self, api, admin, make_user):
        mgr = make_user(role="manager")
        res = api.call("project-requests", "POST", "/", {
            "name": "Zeus", "description": "New platform", "justification": "Growth",
            "proposed_start_date": "2026-01-01", "proposed_end_date": "2026-12-31", "proposed_budget": 25000,
        }, token=mgr["token"])
        assert res.status == 201 and res.json["status"] == "pending"
        rid = res.json["id"]
        assert api.call("project-requests", "POST", f"/{rid}/approve", token=mgr["token"]).status == 403

        res = api.call("project-requests", "POST", f"/{rid}/approve", {"review_note": "Go"}, token=admin["token"])
        assert res.status == 200
        assert res.json["request"]["status"] == "approved" and res.json["request"]["project_code"] == "PRJ-0001"
        project = res.json["project"]
        assert project["manager_id"] == mgr["id"] and project["budget_total"] == 25000
        assert project["start_date"] == "2026-01-01"
        assert api.call("projects", "GET", f"/{project['id']}", token=mgr["token"]).status == 200
        assert api.call("project-requests", "POST", f"/{rid}/approve", token=admin["token"]).status == 409

    def test_reject_requires_note(self, api, admin, make_user):
        mgr = make_user(role="manager")
        rid = api.call("project-requests", "POST", "/", {"name": "Hermes"}, token=mgr["token"]).json["id"]
        assert api.call("project-requests", "POST", f"/{rid}/reject", {}, token=admin["token"]).status == 400
        res = api.call("project-requests", "POST", f"/{rid}/reject", {"review_note": "No budget"},
                       token=admin["token"])
        assert res.status == 200 and res.json["status"] == "rejected" and res.json["review_note"] == "No budget"

    def test_edit_and_withdraw(self, api, admin, make_user):
        mgr = make_user(role="manager")
        rid = api.call("project-requests", "POST", "/", {"name": "Ares"}, token=mgr["token"]).json["id"]
        res = api.call("project-requests", "PUT", f"/{rid}", {"proposed_budget": 10}, token=mgr["token"])
        assert res.status == 200 and res.json["proposed_budget"] == 10
        assert api.call("project-requests", "PUT", f"/{rid}", {"name": "X"}, token=admin["token"]).status == 403
        assert api.call("project-requests", "POST", f"/{rid}/withdraw", token=mgr["token"]).json["status"] == "withdrawn"
        assert api.call("project-requests", "PUT", f"/{rid}", {"name": "X"}, token=mgr["token"]).status == 409

    def test_visibility_and_permissions(self, api, admin, make_user):
        m1, m2 = make_user(role="manager"), make_user(role="manager")
        emp = make_user(manager_id=m1["id"])
        rid = api.call("project-requests", "POST", "/", {"name": "Mine"}, token=m1["token"]).json["id"]
        api.call("project-requests", "POST", "/", {"name": "Theirs"}, token=m2["token"])
        assert api.call("project-requests", "POST", "/", {"name": "X"}, token=emp["token"]).status == 403
        assert api.call("project-requests", "POST", "/", {"name": "X"}, token=admin["token"]).status == 403
        assert api.call("project-requests", "GET", "/", token=emp["token"]).status == 403
        mine = api.call("project-requests", "GET", "/", token=m1["token"]).json["items"]
        assert [r["name"] for r in mine] == ["Mine"]
        assert api.call("project-requests", "GET", f"/{rid}", token=m2["token"]).status == 404
        everything = api.call("project-requests", "GET", "/", token=admin["token"], query={"status": "pending"})
        assert everything.json["total"] == 2

    def test_cannot_approve_for_deactivated_requester(self, api, admin, make_user):
        mgr = make_user(role="manager")
        rid = api.call("project-requests", "POST", "/", {"name": "Orphan"}, token=mgr["token"]).json["id"]
        api.call("users", "PUT", f"/{mgr['id']}", {"is_active": False}, token=admin["token"])
        assert api.call("project-requests", "POST", f"/{rid}/approve", token=admin["token"]).status == 409
