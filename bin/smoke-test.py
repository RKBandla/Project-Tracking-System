#!/usr/bin/env python3
"""
End-to-end smoke test for a running Project Tracking System.

Walks the main business flow through the public API and cleans up after
itself (test users are deactivated and the test projects archived, since
nothing is ever deleted).

Usage:
    bin/smoke-test.py --url http://localhost:3001 --admin-id ADMIN001 --admin-password <pw>
    bin/smoke-test.py --url https://<cloudfront-domain> ...

Uses only the Python standard library.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


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

    def login(self, employee_id: str, password: str) -> str:
        """Return an access token."""
        _, res = self.call("POST", "/auth/login", {"employee_id": employee_id, "password": password}, expect=200)
        return res["access_token"]


def step(message: str) -> None:
    """Print a progress line."""
    print(f"  ✓ {message}", flush=True)


def run(api: Api, admin_id: str, admin_password: str) -> None:
    """Execute the scenario."""
    tag = str(int(time.time()))
    created_users, created_projects = [], []

    admin = api.login(admin_id, admin_password)
    step("admin signed in")
    api.call("GET", "/projects", expect=401)
    step("requests without a token are rejected (401)")

    try:
        _, mgr = api.call("POST", "/users", {
            "first_name": "Smoke", "last_name": f"Manager{tag}", "email": f"smoke.mgr.{tag}@example.com",
            "job_title": "Smoke Manager", "role": "manager",
        }, admin, expect=201)
        created_users.append(mgr["user"]["id"])
        assert len(mgr["temporary_password"]) == 6
        _, emp = api.call("POST", "/users", {
            "first_name": "Smoke", "last_name": f"Employee{tag}", "email": f"smoke.emp.{tag}@example.com",
            "job_title": "Smoke Engineer", "role": "employee", "manager_id": mgr["user"]["id"],
        }, admin, expect=201)
        created_users.append(emp["user"]["id"])
        step(f"created manager {mgr['employee_id']} and employee {emp['employee_id']} with 6-char passwords")

        mgr_token = api.login(mgr["employee_id"], mgr["temporary_password"])
        emp_token = api.login(emp["employee_id"], emp["temporary_password"])
        api.call("POST", "/projects", {"name": "Not allowed"}, mgr_token, expect=403)
        step("manager cannot create projects directly (403)")

        _, req = api.call("POST", "/project-requests", {"name": f"Smoke Project {tag}", "proposed_budget": 1000},
                          mgr_token, expect=201)
        _, approved = api.call("POST", f"/project-requests/{req['id']}/approve", {"review_note": "smoke"}, admin, expect=200)
        project = approved["project"]
        created_projects.append(project["id"])
        assert project["manager_id"] == mgr["user"]["id"]
        step(f"manager request approved -> {project['code']} managed by requester")

        _, other = api.call("POST", "/projects", {"name": f"Smoke Other {tag}", "manager_id": mgr["user"]["id"]},
                            admin, expect=201)
        created_projects.append(other["id"])

        api.call("POST", "/assignments", {"project_id": project["id"], "user_id": emp["user"]["id"],
                                          "hours_per_week": 30}, mgr_token, expect=201)
        _, over = api.call("POST", "/assignments", {"project_id": other["id"], "user_id": emp["user"]["id"],
                                                    "hours_per_week": 15}, mgr_token, expect=409)
        assert over["error"]["details"]["remaining_hours"] == 10
        api.call("POST", "/assignments", {"project_id": other["id"], "user_id": emp["user"]["id"],
                                          "hours_per_week": 10}, mgr_token, expect=201)
        step("40-hour limit enforced (30 h + 15 h rejected, 30 h + 10 h accepted)")

        _, mine = api.call("GET", "/projects", token=emp_token, expect=200)
        assert {p["id"] for p in mine["items"]} == {project["id"], other["id"]}
        assert all("budget_total" not in p for p in mine["items"])
        api.call("GET", "/budgets", token=emp_token, expect=403)
        step("employee sees only assigned projects and no budget data")

        api.call("PUT", "/users/me", {"first_name": "Renamed"}, emp_token, expect=200)
        api.call("PUT", "/users/me", {"job_title": "CEO"}, emp_token, expect=403)
        step("employee can update name/email only")

        api.call("POST", "/deliverables", {"project_id": project["id"], "title": "Smoke deliverable",
                                           "assignee_id": emp["user"]["id"]}, mgr_token, expect=201)
        api.call("POST", "/budgets", {"project_id": project["id"], "category": "labor", "description": "Smoke",
                                      "planned_amount": 500, "actual_amount": 100}, mgr_token, expect=201)
        _, summary = api.call("GET", f"/projects/{project['id']}/summary", token=mgr_token, expect=200)
        assert summary["budget"]["burn_pct"] == 10.0 and summary["team"]["total_hours"] == 30
        step("deliverable and budget item recorded; summary shows 10% budget burn")

        api.call("POST", f"/projects/{project['id']}/archive", token=admin, expect=200)
        api.call("PUT", f"/projects/{project['id']}", {"name": "x"}, admin, expect=409)
        api.call("POST", f"/projects/{project['id']}/reactivate", token=admin, expect=200)
        step("archive makes the project read-only; reactivate restores it")
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
    parser.add_argument("--admin-id", default="ADMIN001")
    parser.add_argument("--admin-password", required=True)
    args = parser.parse_args()
    print(f"Smoke testing {args.url}")
    try:
        run(Api(args.url), args.admin_id, args.admin_password)
    except AssertionError as err:
        print(f"  ✗ {err}", file=sys.stderr)
        return 1
    print("All smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
