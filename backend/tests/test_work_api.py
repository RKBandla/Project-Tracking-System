"""Integration tests for resources (40-hour weeks), deliverable dependencies, timesheets and budgets."""

from datetime import timedelta

import pytest

from .conftest import TODAY, monday


@pytest.fixture
def team(make_user, project_factory):
    """Two managers, two employees (one reporting to each), and projects for the first manager."""
    mgr = make_user(role="manager")
    other_mgr = make_user(role="manager")
    emp = make_user(manager_id=mgr["id"])
    outsider = make_user(manager_id=other_mgr["id"])
    p1 = project_factory(manager_id=mgr["id"], name="Apollo", budget_cents=1_000_000)
    p2 = project_factory(manager_id=mgr["id"], name="Gemini")
    return {"mgr": mgr, "other_mgr": other_mgr, "emp": emp, "outsider": outsider, "p1": p1, "p2": p2}


class TestResources:
    def test_book_for_hours_over_a_date_range(self, api, team, assign):
        res = assign(team["mgr"]["token"], team["p1"], team["emp"], 24, project_role="Developer")
        assert res.status == 201
        a = res.json
        assert (a["hours_per_week"], a["start_date"], a["end_date"]) == (24, str(monday()), str(monday(4) - timedelta(days=1)))
        assert a["planned_cents"] == 24 * 4 * 5000

    def test_41st_hour_refused_naming_conflicting_projects(self, api, team, assign):
        t = team["mgr"]["token"]
        assert assign(t, team["p1"], team["emp"], 30).status == 201
        res = assign(t, team["p2"], team["emp"], 11)
        assert res.status == 409
        err = res.json["error"]
        assert "PRJ-0001 Apollo" in err["message"] and "PRJ-0002 Gemini" in err["message"]
        assert {p["code"] for p in err["details"]["conflicting_projects"]} == {"PRJ-0001", "PRJ-0002"}
        assert err["details"]["weeks"][0]["booked_hours"] == 41
        assert assign(t, team["p2"], team["emp"], 10).status == 201  # exactly 40 is fine

    def test_limit_is_per_week(self, api, team, assign):
        t = team["mgr"]["token"]
        assert assign(t, team["p1"], team["emp"], 40, start=monday(), end=monday(2) - timedelta(days=1)).status == 201
        # the following weeks are free
        assert assign(t, team["p2"], team["emp"], 40, start=monday(2), end=monday(4) - timedelta(days=1)).status == 201
        # overlapping by a single day is a clash in that week
        res = assign(t, team["p2"], team["emp"], 1, start=monday(1) + timedelta(days=4), end=monday(1) + timedelta(days=4))
        assert res.status == 409 and res.json["error"]["details"]["weeks"][0]["week_start"] == str(monday(1))

    def test_managers_book_anyone_onto_their_own_projects(self, api, team, assign, project_factory):
        assert assign(team["mgr"]["token"], team["p1"], team["outsider"], 5).status == 201
        foreign = project_factory(manager_id=team["other_mgr"]["id"], name="Foreign")
        assert assign(team["mgr"]["token"], foreign, team["emp"], 5).status == 404
        assert assign(team["emp"]["token"], team["p1"], team["emp"], 5).status == 404

    def test_validation(self, api, admin, team, assign, make_user):
        t = team["mgr"]["token"]
        assert assign(t, team["p1"], team["emp"], 0).status == 400
        assert assign(t, team["p1"], team["emp"], 41).status == 400
        assert assign(t, team["p1"], team["emp"], 5, start=monday(1), end=monday()).status == 400
        res = assign(t, team["p1"], team["emp"], 5, start=TODAY + timedelta(days=400), end=TODAY + timedelta(days=401))
        assert res.status == 400 and "end_date" in res.json["error"]["details"]
        assert assign(t, team["p1"], make_user(role="admin"), 5).status == 400
        assert assign(t, team["p1"], {"id": 999}, 5).status == 400

    def test_update_archive_and_reactivate(self, api, team, assign):
        t = team["mgr"]["token"]
        a1 = assign(t, team["p1"], team["emp"], 20).json
        assign(t, team["p2"], team["emp"], 20)
        assert api.call("assignments", "PUT", f"/{a1['id']}", {"hours_per_week": 21}, token=t).status == 409
        res = api.call("assignments", "PUT", f"/{a1['id']}", {"hours_per_week": 15, "project_role": "Lead"}, token=t)
        assert res.status == 200 and res.json["hours_per_week"] == 15
        assert api.call("assignments", "DELETE", f"/{a1['id']}", token=t).status == 405
        assert api.call("assignments", "POST", f"/{a1['id']}/archive", token=t).json["is_archived"]
        assert assign(t, team["p2"], team["emp"], 6, start=monday(), end=monday(1)).status == 201  # 26 h booked
        assert api.call("assignments", "POST", f"/{a1['id']}/reactivate", token=t).status == 409  # 26 + 15 = 41
        listed = api.call("assignments", "GET", "/", token=t, query={"archived": "all", "project_id": team["p1"]["id"]})
        assert listed.json["total"] == 1

    def test_employees_see_their_projects_team_without_costs(self, api, team, assign):
        assign(team["mgr"]["token"], team["p1"], team["emp"], 5)
        assign(team["mgr"]["token"], team["p1"], team["outsider"], 5)
        assign(team["mgr"]["token"], team["p2"], team["outsider"], 5)
        res = api.call("assignments", "GET", "/", token=team["emp"]["token"]).json
        assert {a["project_id"] for a in res["items"]} == {team["p1"]["id"]} and res["total"] == 2
        assert all("planned_cents" not in a for a in res["items"])

    def test_allocation_grid(self, api, admin, team, assign):
        t = team["mgr"]["token"]
        assign(t, team["p1"], team["emp"], 30)
        assign(t, team["p2"], team["emp"], 10, start=monday(1), end=monday(2) - timedelta(days=1))
        assign(admin["token"], team["p1"], team["outsider"], 8)
        res = api.call("assignments", "GET", "/grid", token=t, query={"weeks": 4})
        assert res.status == 200
        grid = res.json
        assert grid["weeks"] == [str(monday(i)) for i in range(4)]
        row = next(r for r in grid["rows"] if r["id"] == team["emp"]["id"])
        assert [c["hours"] for c in row["cells"]] == [30, 40, 30, 30]
        assert [c["full"] for c in row["cells"]] == [False, True, False, False]
        assert row["peak_hours"] == 40 and grid["over_allocated_people"] == 0
        assert {p["name"] for p in row["cells"][1]["projects"]} == {"Apollo", "Gemini"}
        names = [r["full_name"] for r in api.call("assignments", "GET", "/grid", token=t, query={"q": "First4"}).json["rows"]]
        assert names == [team["outsider"]["full_name"]]
        assert api.call("assignments", "GET", "/grid", token=team["emp"]["token"]).status == 403
        assert api.call("assignments", "GET", "/grid", token=t, query={"weeks": 40}).status == 400

    def test_grid_hides_other_managers_project_names(self, api, team, assign, project_factory):
        foreign = project_factory(manager_id=team["other_mgr"]["id"], name="Secret")
        assign(team["other_mgr"]["token"], foreign, team["emp"], 10)
        grid = api.call("assignments", "GET", "/grid", token=team["mgr"]["token"], query={"weeks": 1}).json
        cell = next(r for r in grid["rows"] if r["id"] == team["emp"]["id"])["cells"][0]
        assert cell["projects"] == [{"project_id": None, "code": "", "name": "Other projects", "hours": 10}]


class TestDeliverables:
    def create(self, api, token, project, title, **extra):
        res = api.call("deliverables", "POST", "/", {"project_id": project["id"], "title": title, **extra}, token=token)
        assert res.status == 201, res
        return res.json

    def test_dependencies_and_cycle_refusal(self, api, team):
        t = team["mgr"]["token"]
        a = self.create(api, t, team["p1"], "Design")
        b = self.create(api, t, team["p1"], "Build", depends_on=[a["id"]])
        c = self.create(api, t, team["p1"], "Test", depends_on=[b["id"]])
        assert b["depends_on"] == [a["id"]] and b["is_blocked"]
        res = api.call("deliverables", "PUT", f"/{a['id']}", {"depends_on": [c["id"]]}, token=t)
        assert res.status == 409 and res.json["error"]["details"]["cycle"] == [a["id"], c["id"], b["id"], a["id"]]
        assert "Design → Test → Build → Design" in res.json["error"]["message"]
        assert api.call("deliverables", "PUT", f"/{a['id']}", {"depends_on": [a["id"]]}, token=t).status == 400
        other_project = self.create(api, t, team["p2"], "Elsewhere")
        assert api.call("deliverables", "PUT", f"/{a['id']}", {"depends_on": [other_project["id"]]},
                        token=t).status == 400
        assert api.call("deliverables", "PUT", f"/{a['id']}", {"depends_on": "x"}, token=t).status == 400

    def test_cannot_finish_before_dependencies(self, api, team):
        t = team["mgr"]["token"]
        a = self.create(api, t, team["p1"], "Design")
        b = self.create(api, t, team["p1"], "Build", depends_on=[a["id"]])
        res = api.call("deliverables", "PUT", f"/{b['id']}", {"status": "done"}, token=t)
        assert res.status == 409 and "Design (todo)" in res.json["error"]["message"]
        assert api.call("deliverables", "POST", "/", {"project_id": team["p1"]["id"], "title": "X", "status": "done",
                                                      "depends_on": [a["id"]]}, token=t).status == 409
        api.call("deliverables", "PUT", f"/{a['id']}", {"status": "done"}, token=t)
        res = api.call("deliverables", "PUT", f"/{b['id']}", {"status": "done"}, token=t)
        assert res.status == 200 and res.json["progress_pct"] == 100 and not res.json["is_blocked"]

    def test_milestones(self, api, team):
        t, pid = team["mgr"]["token"], team["p1"]["id"]
        due = str(TODAY + timedelta(days=10))
        res = api.call("deliverables", "POST", "/", {"project_id": pid, "title": "Go-live", "is_milestone": True},
                       token=t)
        assert res.status == 400 and "due_date" in res.json["error"]["details"]
        res = api.call("deliverables", "POST", "/", {"project_id": pid, "title": "Go-live", "is_milestone": True,
                                                     "due_date": due, "start_date": str(TODAY)}, token=t)
        assert res.status == 400 and "start_date" in res.json["error"]["details"]
        milestone = self.create(api, t, team["p1"], "Go-live", is_milestone=True, due_date=due)
        assert milestone["is_milestone"] and milestone["start_date"] is None
        work = self.create(api, t, team["p1"], "Build", start_date=str(TODAY), due_date=due)
        assert work["is_milestone"] is False
        get = lambda **q: [d["title"] for d in api.call("deliverables", "GET", "/", token=t, query=q).json["items"]]  # noqa: E731
        assert get(milestone="true") == ["Go-live"] and get(milestone="false") == ["Build"]
        # A ranged deliverable becomes a milestone only once its start date is cleared
        assert api.call("deliverables", "PUT", f"/{work['id']}", {"is_milestone": True}, token=t).status == 400
        res = api.call("deliverables", "PUT", f"/{work['id']}", {"is_milestone": True, "start_date": None}, token=t)
        assert res.status == 200 and res.json["is_milestone"]
        assert api.call("deliverables", "PUT", f"/{milestone['id']}", {"due_date": None}, token=t).status == 400
        res = api.call("deliverables", "PUT", f"/{milestone['id']}", {"is_milestone": None}, token=t)
        assert res.status == 200 and res.json["is_milestone"] is False

    def test_archive_instead_of_delete(self, api, team):
        t = team["mgr"]["token"]
        a = self.create(api, t, team["p1"], "Design")
        b = self.create(api, t, team["p1"], "Build", depends_on=[a["id"]])
        assert api.call("deliverables", "DELETE", f"/{a['id']}", token=t).status == 405
        assert api.call("deliverables", "POST", f"/{a['id']}/archive", token=t).json["is_archived"]
        # an archived dependency no longer blocks
        assert api.call("deliverables", "PUT", f"/{b['id']}", {"status": "done"}, token=t).status == 200
        assert api.call("deliverables", "PUT", f"/{a['id']}", {"title": "X"}, token=t).status == 409
        listed = api.call("deliverables", "GET", "/", token=t, query={"project_id": team["p1"]["id"]}).json
        assert [d["title"] for d in listed["items"]] == ["Build"]
        assert api.call("deliverables", "POST", f"/{a['id']}/reactivate", token=t).status == 200

    def test_graph_levels(self, api, team):
        t = team["mgr"]["token"]
        a = self.create(api, t, team["p1"], "Design")
        b = self.create(api, t, team["p1"], "Build", depends_on=[a["id"]])
        c = self.create(api, t, team["p1"], "Docs", depends_on=[a["id"]])
        d = self.create(api, t, team["p1"], "Launch", depends_on=[b["id"], c["id"]])
        g = api.call("deliverables", "GET", "/graph", token=t, query={"project_id": team["p1"]["id"]}).json
        levels = {n["title"]: n["level"] for n in g["nodes"]}
        assert levels == {"Design": 0, "Build": 1, "Docs": 1, "Launch": 2}
        assert {(e["from"], e["to"]) for e in g["edges"]} == {(a["id"], b["id"]), (a["id"], c["id"]),
                                                              (b["id"], d["id"]), (c["id"], d["id"])}
        assert api.call("deliverables", "GET", "/graph", token=t).status == 400

    def test_filters_and_employee_read_only(self, api, team, assign):
        t = team["mgr"]["token"]
        assign(t, team["p1"], team["emp"], 5)
        self.create(api, t, team["p1"], "Late", due_date=str(TODAY - timedelta(days=1)), assignee_id=team["emp"]["id"])
        self.create(api, t, team["p1"], "Future", due_date=str(TODAY + timedelta(days=30)), status="in_progress")
        get = lambda **q: [d["title"] for d in api.call("deliverables", "GET", "/", token=t, query=q).json["items"]]  # noqa: E731
        assert get(overdue="true") == ["Late"]
        assert get(status="in_progress") == ["Future"]
        assert get(q="fut") == ["Future"]
        et = team["emp"]["token"]
        assert len(api.call("deliverables", "GET", "/", token=et).json["items"]) == 2
        assert api.call("deliverables", "POST", "/", {"project_id": team["p1"]["id"], "title": "X"}, token=et).status == 403
        res = api.call("deliverables", "POST", "/", {"project_id": team["p1"]["id"], "title": "X",
                                                     "assignee_id": team["outsider"]["id"]}, token=t)
        assert res.status == 400


class TestTimesheetsAndBudget:
    def test_logging_rules(self, api, team, assign):
        assign(team["mgr"]["token"], team["p1"], team["emp"], 20)
        et = team["emp"]["token"]
        log = lambda **body: api.call("timesheets", "POST", "/", {"project_id": team["p1"]["id"],  # noqa: E731
                                                                  "work_date": str(monday()), "hours": 8, **body}, token=et)
        assert log().status == 201
        assert log(hours=0.3).status == 400                     # quarter hours only
        assert log(hours=17).status == 409                      # > 24 h that day
        assert log(work_date=str(TODAY + timedelta(days=1))).status == 400  # future
        assert log(project_id=team["p2"]["id"]).status == 400   # not booked on that project
        assert log(work_date=str(monday(-1))).status == 400     # outside the booking
        assert api.call("timesheets", "POST", "/", {"project_id": team["p1"]["id"], "work_date": str(monday()),
                                                    "hours": 1}, token=team["mgr"]["token"]).status == 403

    def test_approval_rights_and_consumed_cost(self, api, admin, team, assign):
        assign(team["mgr"]["token"], team["p1"], team["emp"], 20)
        assign(team["mgr"]["token"], team["p1"], team["outsider"], 20)
        e1 = api.call("timesheets", "POST", "/", {"project_id": team["p1"]["id"], "work_date": str(monday()),
                                                  "hours": 7.5}, token=team["emp"]["token"]).json
        e2 = api.call("timesheets", "POST", "/", {"project_id": team["p1"]["id"], "work_date": str(monday()),
                                                  "hours": 4}, token=team["outsider"]["token"]).json
        budget = lambda: api.call("budgets", "GET", f"/{team['p1']['id']}", token=team["mgr"]["token"]).json  # noqa: E731
        assert budget()["consumed_cents"] == 0  # pending hours don't count

        queue = api.call("timesheets", "GET", "/", token=team["mgr"]["token"], query={"reviewable": "true"}).json
        assert [e["id"] for e in queue["items"]] == [e1["id"]]  # only direct reports
        assert api.call("timesheets", "POST", f"/{e2['id']}/approve", token=team["mgr"]["token"]).status == 404
        assert api.call("timesheets", "POST", f"/{e1['id']}/approve", token=team["emp"]["token"]).status == 403
        assert api.call("timesheets", "POST", f"/{e1['id']}/approve", token=team["mgr"]["token"]).json["status"] == "approved"
        assert api.call("timesheets", "POST", f"/{e1['id']}/approve", token=team["mgr"]["token"]).status == 409
        assert api.call("timesheets", "POST", f"/{e2['id']}/reject", {}, token=admin["token"]).status == 400
        assert api.call("timesheets", "POST", f"/{e2['id']}/reject", {"review_note": "Wrong project"},
                        token=admin["token"]).json["status"] == "rejected"

        b = budget()
        assert b["consumed_cents"] == 37_500  # 7.5 h x $50
        assert b["planned_cents"] == 2 * 20 * 4 * 5000
        assert {p["full_name"]: p["consumed_cents"] for p in b["people"]}[team["emp"]["full_name"]] == 37_500
        assert b["by_month"][0]["consumed_cents"] == 37_500

    def test_edit_withdraw_batch_and_week(self, api, admin, team, assign):
        assign(team["mgr"]["token"], team["p1"], team["emp"], 20)
        et = team["emp"]["token"]
        e1 = api.call("timesheets", "POST", "/", {"project_id": team["p1"]["id"], "work_date": str(monday()),
                                                  "hours": 2}, token=et).json
        e2 = api.call("timesheets", "POST", "/", {"project_id": team["p1"]["id"], "work_date": str(monday()),
                                                  "hours": 3}, token=et).json
        assert api.call("timesheets", "PUT", f"/{e1['id']}", {"hours": 4, "note": "Spec"}, token=et).json["hours"] == 4
        assert api.call("timesheets", "POST", f"/{e2['id']}/withdraw", token=et).json["status"] == "withdrawn"
        assert api.call("timesheets", "DELETE", f"/{e2['id']}", token=et).status == 405
        week = api.call("timesheets", "GET", "/week", token=et).json
        assert week["week_start"] == str(monday()) and week["logged_hours"] == 4 and week["booked_hours"] == 20
        res = api.call("timesheets", "POST", "/approve-batch", {"ids": [e1["id"]]}, token=team["mgr"]["token"])
        assert res.status == 200 and res.json["approved"][0]["status"] == "approved"
        assert api.call("timesheets", "PUT", f"/{e1['id']}", {"hours": 1}, token=et).status == 409
        assert api.call("timesheets", "POST", "/approve-batch", {"ids": []}, token=admin["token"]).status == 400

    def test_budget_rights(self, api, admin, team, assign):
        pid = team["p1"]["id"]
        res = api.call("budgets", "PUT", f"/{pid}", {"budget_cents": 2_000_000}, token=team["mgr"]["token"])
        assert res.status == 200 and res.json["budget_cents"] == 2_000_000 and res.json["remaining_cents"] == 2_000_000
        assert api.call("budgets", "PUT", f"/{pid}", {"budget_cents": 10.5}, token=admin["token"]).status == 400
        assign(team["mgr"]["token"], team["p1"], team["emp"], 5)
        emp_view = api.call("budgets", "GET", f"/{pid}", token=team["emp"]["token"])
        assert emp_view.status == 200 and "people" not in emp_view.json  # totals only, no salaries
        assert api.call("budgets", "PUT", f"/{pid}", {"budget_cents": 1}, token=team["emp"]["token"]).status == 403
        assert api.call("budgets", "GET", f"/{team['p2']['id']}", token=team["emp"]["token"]).status == 404
        listed = api.call("budgets", "GET", "/", token=admin["token"], query={"q": "apollo"}).json
        assert [b["code"] for b in listed["items"]] == ["PRJ-0001"]


class TestAuditAndNotifications:
    def test_each_change_writes_one_audit_row_and_notifies_managers(self, api, admin, team, assign):
        before = api.call("activity", "GET", "/audit", token=admin["token"]).json["total"]
        assign(team["mgr"]["token"], team["p1"], team["emp"], 5)
        log = api.call("activity", "GET", "/audit", token=admin["token"]).json
        assert log["total"] == before + 1
        assert log["items"][0]["summary"].startswith(f"booked {team['emp']['full_name']} on PRJ-0001")
        # the employee logs hours -> their manager is notified
        api.call("timesheets", "POST", "/", {"project_id": team["p1"]["id"], "work_date": str(monday()), "hours": 1},
                 token=team["emp"]["token"])
        notes = api.call("activity", "GET", "/notifications", token=team["mgr"]["token"]).json
        assert notes["unread"] == 1 and notes["items"][0]["message"].startswith(team["emp"]["full_name"] + " logged 1")
        assert api.call("activity", "POST", f"/notifications/{notes['items'][0]['id']}/read",
                        token=team["mgr"]["token"]).json["read_at"]
        assert api.call("activity", "GET", "/notifications", token=team["mgr"]["token"],
                        query={"unread": "true"}).json["total"] == 0
        assert api.call("activity", "POST", f"/notifications/{notes['items'][0]['id']}/read",
                        token=team["emp"]["token"]).status == 404

    def test_notifications_reach_the_whole_chain(self, api, admin, make_user, project_factory, assign):
        boss = make_user(role="manager")
        mgr = make_user(role="manager", manager_id=boss["id"])
        project = project_factory(manager_id=mgr["id"])
        emp = make_user()
        assign(mgr["token"], project, emp, 5)
        assert api.call("activity", "GET", "/notifications", token=boss["token"]).json["unread"] == 1
        assert api.call("activity", "POST", "/notifications/read-all", token=boss["token"]).json["unread"] == 0

    def test_audit_is_admin_only_and_filterable(self, api, admin, team):
        assert api.call("activity", "GET", "/audit", token=team["mgr"]["token"]).status == 403
        res = api.call("activity", "GET", "/audit", token=admin["token"], query={"entity": "project", "q": "Apollo"})
        assert res.status == 200 and res.json["items"][0]["action"] == "create"
        assert api.call("activity", "GET", "/audit", token=admin["token"], query={"entity": "x"}).status == 400

    @pytest.mark.parametrize("service", ["users", "projects", "project-requests", "assignments", "deliverables",
                                         "budgets", "timesheets"])
    def test_there_is_no_delete_route(self, api, admin, service):
        assert api.call(service, "DELETE", "/1", token=admin["token"]).status in (404, 405)
