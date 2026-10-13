"""
Assignments (resources) service: book people onto projects for N hours per week
over a date range, plus the allocation grid.

Routes (relative to /api/assignments):
    GET  /                  list assignments (search, filters, pagination)
    GET  /grid              allocation grid: people down, weeks across (admin, manager)
    POST /                  book a person onto a project
    GET  /{id}              view assignment
    PUT  /{id}              change hours, dates or project role
    POST /{id}/archive      end the booking (nothing is deleted)
    POST /{id}/reactivate   restore an archived booking

Rules:
- admins book anyone onto any project; managers book anyone in the company onto
  projects they manage;
- nobody is booked over 40 hours in any week (409 naming the conflicting projects).
"""

from datetime import date, timedelta

from shared import audit
from shared.app import make_handler
from shared.errors import bad_request, conflict, not_found
from shared.http import Request, Router, response
from shared.projects import PLANNED_COST_SQL
from shared.query import Filters, choice_param, date_param, int_param, order_by, paginated
from shared.rbac import ADMIN, EMPLOYEE, MANAGER, load_managed_project, require_role, visible_project_ids
from shared.rules import MAX_WEEKLY_HOURS, assert_within_capacity, lock_user
from shared.users import get_user
from shared.validation import Field, check_date_range, validate

router = Router()

CREATE_SCHEMA = {
    "project_id": Field(kind="int", required=True, min_value=1),
    "user_id": Field(kind="int", required=True, min_value=1),
    "hours_per_week": Field(kind="int", required=True, min_value=1, max_value=MAX_WEEKLY_HOURS),
    "start_date": Field(kind="date", required=True),
    "end_date": Field(kind="date", required=True),
    "project_role": Field(max_length=100),
}
UPDATE_SCHEMA = {k: v for k, v in CREATE_SCHEMA.items() if k not in ("project_id", "user_id")}

# Built only from constant SQL fragments; no request data is interpolated.
SELECT = f"""
    SELECT a.id, a.project_id, a.user_id, a.project_role, a.hours_per_week, a.start_date, a.end_date,
           a.is_archived, a.archived_at, a.assigned_by, a.created_at, a.updated_at,
           p.code AS project_code, p.name AS project_name, p.is_archived AS project_is_archived,
           p.manager_id AS project_manager_id,
           u.employee_id, u.first_name || ' ' || u.last_name AS full_name, u.job_title,
           u.manager_id AS user_manager_id,
           {PLANNED_COST_SQL} AS planned_cents
    FROM project_assignments a
    JOIN projects p ON p.id = a.project_id
    JOIN users u ON u.id = a.user_id
"""  # nosec B608
SORTS = {"full_name": "full_name", "project_name": "project_name", "hours_per_week": "hours_per_week",
         "start_date": "start_date", "end_date": "end_date", "created_at": "created_at"}


def _scope(user: dict, filters: Filters) -> Filters:
    """Admins see all; managers their projects and direct reports; employees their projects' teams."""
    if user["role"] == MANAGER:
        filters.add("(project_manager_id = %s OR user_manager_id = %s)", user["id"], user["id"])
    elif user["role"] == EMPLOYEE:
        sql, params = visible_project_ids(user)
        filters.add(f"(project_id IN ({sql}) OR user_id = %s)", *params, user["id"])
    return filters


def _present(row: dict, user: dict) -> dict:
    """Hide salary-derived cost from employees."""
    if user["role"] == EMPLOYEE:
        return {k: v for k, v in row.items() if k != "planned_cents"}
    return row


def _load(cur, user: dict, assignment_id: int) -> dict:
    """Fetch an assignment visible to the user or raise 404."""
    filters = _scope(user, Filters()).eq("id", assignment_id)
    cur.execute(f"SELECT * FROM ({SELECT}) AS t {filters.where()}", filters.params)  # nosec B608
    row = cur.fetchone()
    if row is None:
        raise not_found("Assignment")
    return row


def _check_dates(project: dict, start: date, end: date) -> None:
    """Bookings must be ordered and fall inside the project's dates when it has them."""
    check_date_range(start, end)
    errors = {}
    if project["start_date"] and start < project["start_date"]:
        errors["start_date"] = f"must be on or after the project start ({project['start_date'].isoformat()})"
    if project["end_date"] and end > project["end_date"]:
        errors["end_date"] = f"must be on or before the project end ({project['end_date'].isoformat()})"
    if errors:
        raise bad_request("Validation failed", errors)


def _label(row: dict) -> str:
    """'Eli Engineer on PRJ-0001' for audit summaries."""
    return f"{row['full_name']} on {row['project_code']}"


@router.get("/")
def list_assignments(request: Request, cur) -> dict:
    """List assignments with filters."""
    user, q = request.user, request.query
    filters = _scope(user, Filters())
    filters.eq("project_id", int_param(q, "project_id"))
    filters.eq("user_id", int_param(q, "user_id"))
    archived = choice_param(q, "archived", ("true", "false", "all")) or "false"
    if archived != "all":
        filters.eq("is_archived", archived == "true")
    active_on = date_param(q, "active_on")
    if active_on:
        filters.add("start_date <= %s AND end_date >= %s", active_on, active_on)
    filters.search(["full_name", "employee_id", "project_name", "project_code", "project_role"], q.get("q"))
    result = paginated(cur, SELECT, filters, order_by(q, SORTS, "start_date"), q)
    result["items"] = [_present(row, user) for row in result["items"]]
    return response(200, result)


@router.get("/grid")
def grid(request: Request, cur) -> dict:
    """
    Allocation grid: one row per active person, one column per week, each cell the
    booked hours (flagged when at or over 40). Project names are shown only for
    projects the viewer can see; other bookings are grouped as "Other projects".
    """
    user, q = request.user, request.query
    require_role(user, ADMIN, MANAGER)
    start = date_param(q, "from") or date.today()
    start = start - timedelta(days=start.weekday())
    weeks = int_param(q, "weeks") or 12
    if not 1 <= weeks <= 26:
        raise bad_request("Validation failed", {"weeks": "must be between 1 and 26"})
    end = start + timedelta(weeks=weeks, days=-1)
    week_starts = [start + timedelta(weeks=i) for i in range(weeks)]

    people_filters = Filters(clauses=["is_active", "role <> 'admin'"])
    people_filters.search(["full_name", "employee_id", "job_title"], q.get("q"))
    if choice_param(q, "only_over", ("true", "false")) == "true":
        people_filters.add(
            """id IN (SELECT a.user_id FROM project_assignments a JOIN projects p ON p.id = a.project_id
                      WHERE NOT a.is_archived AND NOT p.is_archived AND a.start_date <= %s AND a.end_date >= %s)""",
            end, start,
        )
    people = paginated(
        cur,
        "SELECT id, employee_id, first_name || ' ' || last_name AS full_name, job_title, role, is_active "
        "FROM users",
        people_filters, order_by({"sort": q.get("sort") or "full_name"}, {"full_name": "full_name"}, "full_name"),
        {"page": q.get("page"), "page_size": q.get("page_size") or "50"},
    )
    ids = [p["id"] for p in people["items"]]
    visible = visible_project_ids(user)
    cur.execute(
        """
        SELECT a.user_id, a.project_id, p.code, p.name, a.hours_per_week, a.start_date, a.end_date,
               (%s OR p.manager_id = %s) AS visible
        FROM project_assignments a JOIN projects p ON p.id = a.project_id
        WHERE a.user_id = ANY(%s::int[]) AND NOT a.is_archived AND NOT p.is_archived
          AND a.start_date <= %s AND a.end_date >= %s
        """,
        [visible is None, user["id"], ids, end, start],
    )
    bookings = cur.fetchall()

    rows = []
    over_people = 0
    for person in people["items"]:
        cells = []
        for week_start in week_starts:
            week_end = week_start + timedelta(days=6)
            items: dict = {}
            for b in bookings:
                if b["user_id"] != person["id"] or b["start_date"] > week_end or b["end_date"] < week_start:
                    continue
                key = b["project_id"] if b["visible"] else "other"
                entry = items.setdefault(key, {
                    "project_id": b["project_id"] if b["visible"] else None,
                    "code": b["code"] if b["visible"] else "",
                    "name": b["name"] if b["visible"] else "Other projects",
                    "hours": 0,
                })
                entry["hours"] += b["hours_per_week"]
            hours = sum(i["hours"] for i in items.values())
            cells.append({
                "week_start": week_start,
                "hours": hours,
                "full": hours >= MAX_WEEKLY_HOURS,
                "over": hours > MAX_WEEKLY_HOURS,
                "projects": list(items.values()),
            })
        if any(c["over"] for c in cells):
            over_people += 1
        rows.append({**person, "cells": cells, "peak_hours": max(c["hours"] for c in cells)})

    return response(200, {
        "weeks": week_starts,
        "max_hours": MAX_WEEKLY_HOURS,
        "rows": rows,
        "over_allocated_people": over_people,
        "total": people["total"],
        "page": people["page"],
        "page_size": people["page_size"],
    })


@router.post("/")
def create_assignment(request: Request, cur) -> dict:
    """Book a person onto a project for N hours per week between two dates."""
    user = request.user
    data = validate(request.body, CREATE_SCHEMA)
    project = load_managed_project(cur, user, data["project_id"])
    _check_dates(project, data["start_date"], data["end_date"])
    assignee = get_user(cur, data["user_id"])
    if assignee is None:
        raise bad_request("Validation failed", {"user_id": "user does not exist"})
    if not assignee["is_active"] or assignee["role"] not in (EMPLOYEE, MANAGER):
        raise bad_request("Validation failed", {"user_id": "must be an active employee or manager"})
    lock_user(cur, assignee["id"])
    cur.execute(
        """
        INSERT INTO project_assignments (project_id, user_id, project_role, hours_per_week,
                                         start_date, end_date, assigned_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        [project["id"], assignee["id"], data["project_role"] or "", data["hours_per_week"],
         data["start_date"], data["end_date"], user["id"]],
    )
    assignment_id = cur.fetchone()["id"]
    assert_within_capacity(cur, assignee["id"], data["start_date"], data["end_date"])
    row = _load(cur, user, assignment_id)
    audit.record(cur, user, "assignment", assignment_id, "create",
                 f"booked {_label(row)} for {data['hours_per_week']} h/week "
                 f"({data['start_date'].isoformat()} to {data['end_date'].isoformat()})", data)
    return response(201, _present(row, user))


@router.get("/{id}")
def get_one(request: Request, cur) -> dict:
    """View an assignment."""
    user = request.user
    return response(200, _present(_load(cur, user, request.params["id"]), user))


@router.put("/{id}")
def update_assignment(request: Request, cur) -> dict:
    """Change hours, dates or project role."""
    user = request.user
    row = _load(cur, user, request.params["id"])
    project = load_managed_project(cur, user, row["project_id"])
    if row["is_archived"]:
        raise conflict("Assignment is archived; reactivate it first")
    data = validate(request.body, UPDATE_SCHEMA, partial=True)
    if not data:
        raise bad_request("Nothing to update")
    missing = {k: "is required" for k in ("hours_per_week", "start_date", "end_date") if k in data and data[k] is None}
    if missing:
        raise bad_request("Validation failed", missing)
    if "project_role" in data and data["project_role"] is None:
        data["project_role"] = ""
    start = data.get("start_date", row["start_date"])
    end = data.get("end_date", row["end_date"])
    _check_dates(project, start, end)
    lock_user(cur, row["user_id"])
    assignments = ", ".join(f"{name} = %s" for name in data)
    cur.execute(f"UPDATE project_assignments SET {assignments}, updated_at = now() WHERE id = %s",  # nosec B608
                [*data.values(), row["id"]])
    assert_within_capacity(cur, row["user_id"], start, end)
    changes = audit.diff(row, data)
    audit.record(cur, user, "assignment", row["id"], "update", f"changed the booking of {_label(row)}", changes)
    return response(200, _present(_load(cur, user, row["id"]), user))


@router.post("/{id}/archive")
def archive_assignment(request: Request, cur) -> dict:
    """End a booking. The record stays for cost history."""
    user = request.user
    row = _load(cur, user, request.params["id"])
    load_managed_project(cur, user, row["project_id"])
    if row["is_archived"]:
        raise conflict("Assignment is already archived")
    cur.execute("UPDATE project_assignments SET is_archived = TRUE, archived_at = now(), updated_at = now() "
                "WHERE id = %s", [row["id"]])
    audit.record(cur, user, "assignment", row["id"], "archive", f"removed {_label(row)}")
    return response(200, _present(_load(cur, user, row["id"]), user))


@router.post("/{id}/reactivate")
def reactivate_assignment(request: Request, cur) -> dict:
    """Restore an archived booking, re-checking the 40-hour limit."""
    user = request.user
    row = _load(cur, user, request.params["id"])
    load_managed_project(cur, user, row["project_id"])
    if not row["is_archived"]:
        raise conflict("Assignment is not archived")
    lock_user(cur, row["user_id"])
    cur.execute("UPDATE project_assignments SET is_archived = FALSE, archived_at = NULL, updated_at = now() "
                "WHERE id = %s", [row["id"]])
    assert_within_capacity(cur, row["user_id"], row["start_date"], row["end_date"])
    audit.record(cur, user, "assignment", row["id"], "update", f"restored {_label(row)}")
    return response(200, _present(_load(cur, user, row["id"]), user))


handler = make_handler(router, "assignments")
