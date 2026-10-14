#!/usr/bin/env python3
"""
Load demo data through the public API so every screen has something to show.

Creates two managers, four employees, three projects (one on track, one late,
one burning budget too fast), dated bookings, deliverables with dependencies,
logged hours (some approved, some waiting) and a pending project request, then
prints the sign-in details. Run it once against a fresh database.

Usage:
    bin/seed-demo.py --url http://localhost:3001 --admin-email admin@pts.local --admin-password <pw>

Uses only the Python standard library.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta


class Api:
    """Tiny JSON client that raises on unexpected status codes."""

    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/") + "/api"

    def call(self, method: str, path: str, body=None, token=None):
        """Send a request and return the JSON body; raise on >= 400."""
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=60) as res:  # nosec B310 - URL comes from the operator
                raw = res.read()
        except urllib.error.HTTPError as err:
            raise SystemExit(f"{method} {path} failed ({err.code}): {err.read().decode()}") from err
        return json.loads(raw) if raw else None

    def login(self, email: str, password: str) -> str:
        """Return an access token."""
        return self.call("POST", "/auth/login", {"email": email, "password": password})["access_token"]


def main() -> int:
    """Create the demo data and print the logins."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True)
    parser.add_argument("--admin-email", default="admin@pts.local")
    parser.add_argument("--admin-password", required=True)
    args = parser.parse_args()
    api = Api(args.url)
    admin = api.login(args.admin_email, args.admin_password)

    existing = api.call("GET", "/users?q=mia.manager%40demo.local", token=admin)
    if existing["total"]:
        print("Demo data already exists (mia.manager@demo.local). Nothing to do.")
        return 0

    today = date.today()
    monday = today - timedelta(days=today.weekday())
    logins = [("Admin", args.admin_email, args.admin_password)]

    def user(first, last, role, title, salary, manager_id=None):
        res = api.call("POST", "/users", {
            "first_name": first, "last_name": last, "email": f"{first.lower()}.{last.lower()}@demo.local",
            "job_title": title, "role": role, "salary_cents": salary * 100, "manager_id": manager_id,
        }, admin)
        logins.append((f"{role.title()} ({first} {last})", res["user"]["email"], res["temporary_password"]))
        return {**res["user"], "token": api.login(res["user"]["email"], res["temporary_password"])}

    mia = user("Mia", "Manager", "manager", "Delivery Manager", 135_000)
    omar = user("Omar", "Okafor", "manager", "Engineering Manager", 140_000)
    eli = user("Eli", "Engineer", "employee", "Software Engineer", 104_000, mia["id"])
    sara = user("Sara", "Singh", "employee", "QA Analyst", 83_200, mia["id"])
    leo = user("Leo", "Lopez", "employee", "Designer", 93_600, omar["id"])
    user("Ava", "Adams", "employee", "Data Analyst", 99_840, omar["id"])

    def project(name, manager, start, end, budget_dollars, status="active", description=""):
        return api.call("POST", "/projects", {
            "name": name, "description": description, "status": status, "manager_id": manager["id"],
            "start_date": str(start), "end_date": str(end), "budget_cents": budget_dollars * 100,
        }, admin)

    portal = project("Customer Portal", mia, monday - timedelta(weeks=6), monday + timedelta(weeks=10), 120_000,
                     description="Self-service portal for customers to track orders and invoices.")
    migration = project("Data Migration", omar, monday - timedelta(weeks=10), today - timedelta(days=3), 40_000,
                        description="Move legacy reports to the new warehouse.")
    mobile = project("Mobile App", mia, monday - timedelta(weeks=2), monday + timedelta(weeks=2), 1_000,
                     description="Companion app; budget is tight.")

    def book(manager, proj, person, hours, start, end, role):
        api.call("POST", "/assignments", {"project_id": proj["id"], "user_id": person["id"], "hours_per_week": hours,
                                          "start_date": str(start), "end_date": str(end), "project_role": role},
                 manager["token"])

    book(mia, portal, eli, 30, monday - timedelta(weeks=6), monday + timedelta(weeks=10, days=-1), "Backend developer")
    book(mia, portal, sara, 20, monday - timedelta(weeks=2), monday + timedelta(weeks=8, days=-1), "QA")
    book(mia, portal, leo, 10, monday, monday + timedelta(weeks=4, days=-1), "UI design")
    book(omar, migration, leo, 20, monday - timedelta(weeks=10), today - timedelta(days=3), "Data mapping")
    book(mia, mobile, eli, 10, monday - timedelta(weeks=2), monday + timedelta(weeks=2, days=-1), "Mobile developer")
    book(mia, mobile, sara, 20, monday + timedelta(weeks=1), monday + timedelta(weeks=2, days=-1), "QA")

    def deliverable(manager, proj, title, **fields):
        return api.call("POST", "/deliverables", {"project_id": proj["id"], "title": title, **fields}, manager["token"])

    design = deliverable(mia, portal, "UX design", status="done", assignee_id=leo["id"],
                         start_date=str(monday - timedelta(weeks=6)), due_date=str(monday - timedelta(weeks=4)))
    api_d = deliverable(mia, portal, "Orders API", status="in_progress", progress_pct=60, assignee_id=eli["id"],
                        start_date=str(monday - timedelta(weeks=4)), due_date=str(monday + timedelta(weeks=2)),
                        depends_on=[design["id"]])
    ui = deliverable(mia, portal, "Portal UI", status="todo", assignee_id=eli["id"],
                     start_date=str(monday + timedelta(weeks=1)), due_date=str(monday + timedelta(weeks=6)),
                     depends_on=[design["id"], api_d["id"]])
    tests = deliverable(mia, portal, "Acceptance testing", assignee_id=sara["id"],
                        start_date=str(monday + timedelta(weeks=6)), due_date=str(monday + timedelta(weeks=9)),
                        depends_on=[ui["id"]])
    deliverable(mia, portal, "Go-live", is_milestone=True, due_date=str(monday + timedelta(weeks=10)),
                depends_on=[tests["id"]])
    deliverable(omar, migration, "Report mapping", status="in_progress", progress_pct=80, assignee_id=leo["id"],
                due_date=str(today - timedelta(days=5)))
    deliverable(mia, mobile, "Prototype", status="in_progress", progress_pct=40, assignee_id=eli["id"],
                due_date=str(monday + timedelta(weeks=1)))

    def log(person, proj, day, hours, note):
        return api.call("POST", "/timesheets", {"project_id": proj["id"], "work_date": str(day), "hours": hours,
                                                "note": note}, person["token"])

    approved = []
    for back in range(1, 4):
        week = monday - timedelta(weeks=back)
        for d in range(5):
            approved.append(log(eli, portal, week + timedelta(days=d), 6, "Orders API")["id"])
            approved.append(log(eli, mobile, week + timedelta(days=d), 2, "Prototype")["id"] if back <= 2 else None)
    approved = [a for a in approved if a]
    for chunk in range(0, len(approved), 100):
        api.call("POST", "/timesheets/approve-batch", {"ids": approved[chunk:chunk + 100]}, mia["token"])
    for d in range(min(today.weekday() + 1, 5)):
        log(eli, portal, monday + timedelta(days=d), 6, "Orders API")
        log(sara, portal, monday + timedelta(days=d), 4, "Test plan")

    api.call("POST", "/project-requests", {
        "name": "Analytics Dashboard", "justification": "Leadership wants weekly KPIs in one place.",
        "proposed_start_date": str(monday + timedelta(weeks=4)), "proposed_end_date": str(monday + timedelta(weeks=16)),
        "proposed_budget_cents": 60_000_00,
    }, mia["token"])

    print("Demo data created.\n")
    print(f"{'Role':<28} {'Email':<28} Password")
    for role, email, password in logins:
        print(f"{role:<28} {email:<28} {password}")
    print("\nCustomer Portal is on track, Data Migration is late, Mobile App is burning budget too fast.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
