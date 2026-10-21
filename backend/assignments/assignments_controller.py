"""
Assignments CONTROLLER: the routes for bookings and the allocation grid.

Each route reads the request, checks permissions and rules, calls the model
(assignments_model) for data and returns a view (assignments_view).

Nobody is booked over 40 hours in any week: every write locks the person,
saves, then re-checks capacity (409 naming the conflicting projects).
"""

from datetime import date, timedelta

import assignments_model as model
import assignments_view as view
from shared import audit
from shared.errors import bad_request, conflict, not_found
from shared.http import Request, Router
from shared.query import Filters, choice_param, date_param, int_param, order_by
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


def _scope(user: dict, filters: Filters) -> Filters:
    """Admins see all; managers their projects and direct reports; employees their projects' teams."""
    if user["role"] == MANAGER:
        filters.add("(project_manager_id = %s OR user_manager_id = %s)", user["id"], user["id"])
    elif user["role"] == EMPLOYEE:
        sql, params = visible_project_ids(user)
        filters.add(f"(project_id IN ({sql}) OR user_id = %s)", *params, user["id"])
    return filters


def _load(cur, user: dict, assignment_id: int) -> dict:
    """Fetch an assignment visible to the user or raise 404."""
    row = model.find_assignment(cur, _scope(user, Filters()).eq("id", assignment_id))
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
    return view.assignment_list(model.list_assignments(cur, filters, order_by(q, model.SORTS, "start_date"), q), user)


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
        people_filters.add(model.BOOKED_BETWEEN_SQL, end, start)
    people = model.list_grid_people(
        cur, people_filters,
        order_by({"sort": q.get("sort") or "full_name"}, model.GRID_PEOPLE_SORTS, "full_name"),
        {"page": q.get("page"), "page_size": q.get("page_size") or "50"},
    )
    ids = [p["id"] for p in people["items"]]
    visible = visible_project_ids(user)
    bookings = model.grid_bookings(cur, ids, start, end, visible is None, user["id"])
    return view.grid(week_starts, people, bookings)


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
    assignment_id = model.insert_assignment(cur, project["id"], assignee["id"], data, user["id"])
    assert_within_capacity(cur, assignee["id"], data["start_date"], data["end_date"])
    row = _load(cur, user, assignment_id)
    audit.record(cur, user, "assignment", assignment_id, "create",
                 f"booked {_label(row)} for {data['hours_per_week']} h/week "
                 f"({data['start_date'].isoformat()} to {data['end_date'].isoformat()})", data)
    return view.assignment(row, user, 201)


@router.get("/{id}")
def get_one(request: Request, cur) -> dict:
    """View an assignment."""
    user = request.user
    return view.assignment(_load(cur, user, request.params["id"]), user)


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
    model.update_assignment(cur, row["id"], data)
    assert_within_capacity(cur, row["user_id"], start, end)
    changes = audit.diff(row, data)
    audit.record(cur, user, "assignment", row["id"], "update", f"changed the booking of {_label(row)}", changes)
    return view.assignment(_load(cur, user, row["id"]), user)


@router.post("/{id}/archive")
def archive_assignment(request: Request, cur) -> dict:
    """End a booking. The record stays for cost history."""
    user = request.user
    row = _load(cur, user, request.params["id"])
    load_managed_project(cur, user, row["project_id"])
    if row["is_archived"]:
        raise conflict("Assignment is already archived")
    model.archive_assignment(cur, row["id"])
    audit.record(cur, user, "assignment", row["id"], "archive", f"removed {_label(row)}")
    return view.assignment(_load(cur, user, row["id"]), user)


@router.post("/{id}/reactivate")
def reactivate_assignment(request: Request, cur) -> dict:
    """Restore an archived booking, re-checking the 40-hour limit."""
    user = request.user
    row = _load(cur, user, request.params["id"])
    load_managed_project(cur, user, row["project_id"])
    if not row["is_archived"]:
        raise conflict("Assignment is not archived")
    lock_user(cur, row["user_id"])
    model.reactivate_assignment(cur, row["id"])
    assert_within_capacity(cur, row["user_id"], row["start_date"], row["end_date"])
    audit.record(cur, user, "assignment", row["id"], "update", f"restored {_label(row)}")
    return view.assignment(_load(cur, user, row["id"]), user)
