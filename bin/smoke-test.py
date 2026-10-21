#!/usr/bin/env python3
"""
End-to-end smoke test for a running Project Tracking System.

Walks the main business flow through the public API, demonstrating each rule
as a refusal, then cleans up after itself (test users are deactivated and the
test projects archived, since nothing is ever deleted).

Usage:
    bin/smoke-test.py --url http://localhost:3001 --admin-email admin@pts.local --admin-password <pw>
    bin/smoke-test.py --url https://<cloudfront-domain> ...

Uses only the Python standard library.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta


class Api:
    """Tiny JSON client."""

    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/") + "/api"

    def call(self, method: str, path: str, body=None, token=None, expect=None):
        """Send a request; return (status, json). Asserts on ``expect`` if given."""
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=60) as res:  # nosec B310 - URL comes from the operator
                status, raw = res.status, res.read()
        except urllib.error.HTTPError as err:
            status, raw = err.code, err.read()
        payload = json.loads(raw) if raw else None
        if expect is not None and status != expect:
            raise AssertionError(f"{method} {path}: expected {expect}, got {status}: {payload}")
        return status, payload

    def login(self, email: str, password: str) -> str:
        """Return an access token."""
        _, res = self.call("POST", "/auth/login", {"email": email, "password": password}, expect=200)
        return res["access_token"]


def step(message: str) -> None:
    """Print a progress line."""
    print(f"  ✓ {message}", flush=True)


def run(api: Api, admin_email: str, admin_password: str) -> None:
    """Execute the scenario."""
    tag = str(int(time.time()))
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    month_end = monday + timedelta(weeks=4, days=-1)
    created_users, created_projects = [], []

    admin = api.login(admin_email, admin_password)
    step("admin signed in with email")
    api.call("GET", "/projects", expect=401)
    step("requests without a token are refused (401)")

    try:
        def create_user(role, last, manager_id=None):
            _, res = api.call("POST", "/users", {
                "first_name": "Smoke", "last_name": f"{last}{tag}", "email": f"smoke.{last.lower()}.{tag}@example.com",
                "job_title": f"Smoke {last}", "role": role, "salary_cents": 10_400_000, "manager_id": manager_id,
            }, admin, expect=201)
            created_users.append(res["user"]["id"])
            assert len(res["temporary_password"]) == 6
            return res

        mgr = create_user("manager", "Manager")
        emp = create_user("employee", "Employee", mgr["user"]["id"])
        other = create_user("employee", "Other")
        step("created a manager and two employees ($104,000 salary = $50/h)")
        mgr_token = api.login(mgr["user"]["email"], mgr["temporary_password"])
        emp_token = api.login(emp["user"]["email"], emp["temporary_password"])

        api.call("POST", "/projects", {"name": "Not allowed"}, mgr_token, expect=403)
        _, req = api.call("POST", "/project-requests", {"name": f"Smoke {tag}", "proposed_budget_cents": 1_000_000},
                          mgr_token, expect=201)
        _, approved = api.call("POST", f"/project-requests/{req['id']}/approve", {}, admin, expect=200)
        project = approved["project"]
        created_projects.append(project["id"])
        step(f"manager can't create projects (403); request approved -> {project['code']}")

        _, second = api.call("POST", "/projects", {"name": f"Smoke B {tag}", "manager_id": mgr["user"]["id"]},
                             admin, expect=201)
        created_projects.append(second["id"])
        api.call("PUT", f"/projects/{project['id']}", {"name": "x"}, mgr_token, expect=403)
        api.call("PUT", f"/projects/{project['id']}", {"status": "active"}, mgr_token, expect=200)
        step("manager edits only description and status")

        book = {"start_date": str(monday), "end_date": str(month_end)}
        api.call("POST", "/assignments", {"project_id": project["id"], "user_id": emp["user"]["id"],
                                          "hours_per_week": 30, **book}, mgr_token, expect=201)
        _, refused = api.call("POST", "/assignments", {"project_id": second["id"], "user_id": emp["user"]["id"],
                                                       "hours_per_week": 11, **book}, mgr_token, expect=409)
        assert project["code"] in refused["error"]["message"]
        api.call("POST", "/assignments", {"project_id": second["id"], "user_id": other["user"]["id"],
                                          "hours_per_week": 10, **book}, mgr_token, expect=201)
        step("41st hour refused (409) naming the conflicting projects; managers book anyone")

        _, a = api.call("POST", "/deliverables", {"project_id": project["id"], "title": "Design"}, mgr_token, expect=201)
        _, b = api.call("POST", "/deliverables", {"project_id": project["id"], "title": "Build",
                                                  "depends_on": [a["id"]]}, mgr_token, expect=201)
        api.call("PUT", f"/deliverables/{a['id']}", {"depends_on": [b["id"]]}, mgr_token, expect=409)
        api.call("PUT", f"/deliverables/{b['id']}", {"status": "done"}, mgr_token, expect=409)
        step("dependency loop refused; can't finish before dependencies")

        _, entry = api.call("POST", "/timesheets", {"project_id": project["id"], "work_date": str(monday),
                                                    "hours": 8}, emp_token, expect=201)
        _, budget = api.call("GET", f"/budgets/{project['id']}", token=mgr_token, expect=200)
        assert budget["consumed_cents"] == 0 and budget["planned_cents"] == 30 * 4 * 5000
        api.call("POST", f"/timesheets/{entry['id']}/approve", {}, mgr_token, expect=200)
        _, budget = api.call("GET", f"/budgets/{project['id']}", token=mgr_token, expect=200)
        assert budget["consumed_cents"] == 8 * 5000
        step("planned cost $6,000 from bookings; consumed $400 only after approval")

        _, notes = api.call("GET", "/activity/notifications", token=mgr_token, expect=200)
        assert notes["unread"] >= 1
        _, log = api.call("GET", "/activity/audit", token=admin, expect=200)
        assert log["total"] > 0
        api.call("GET", "/activity/audit", token=mgr_token, expect=403)
        api.call("DELETE", f"/projects/{project['id']}", token=admin, expect=405)
        step("manager notified of employee's change; audit log is admin-only; no DELETE route")

        api.call("POST", f"/projects/{project['id']}/archive", token=admin, expect=200)
        api.call("PUT", f"/projects/{project['id']}", {"name": "x"}, admin, expect=409)
        api.call("POST", f"/projects/{project['id']}/reactivate", token=admin, expect=200)
        step("archived project is read-only; reactivated")
    finally:
        for project_id in created_projects:
            api.call("POST", f"/projects/{project_id}/archive", token=admin)
        for user_id in reversed(created_users):
            api.call("PUT", f"/users/{user_id}", {"is_active": False}, admin)
        if created_users or created_projects:
            step("cleaned up (test projects archived, test users deactivated)")


def main() -> int:
    """Parse arguments and run."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True, help="Base URL (proxy or CloudFront), without /api")
    parser.add_argument("--admin-email", default="admin@pts.local")
    parser.add_argument("--admin-password", required=True)
    args = parser.parse_args()
    print(f"Smoke testing {args.url}")
    try:
        run(Api(args.url), args.admin_email, args.admin_password)
    except AssertionError as err:
        print(f"  ✗ {err}", file=sys.stderr)
        return 1
    print("All smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
