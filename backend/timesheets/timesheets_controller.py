"""
Timesheets CONTROLLER: the routes for logging and approving hours.

Each route reads the request, checks permissions and rules, calls the model
(timesheets_model) for data and returns a view (timesheets_view).

Hours are quarter hours, never in the future, only on a project the person
is booked on that day, and at most 24 per day (pending + approved).
"""

from datetime import date, timedelta
from decimal import Decimal

import timesheets_model as model
import timesheets_view as view
from shared import audit
from shared.errors import bad_request, conflict, forbidden, not_found
from shared.http import Request, Router
from shared.query import Filters, choice_param, date_param, int_param, order_by
from shared.rbac import ADMIN, EMPLOYEE, MANAGER, require_role
from shared.schema import TIME_ENTRY_STATUSES
from shared.validation import Field, validate

router = Router()

MAX_HOURS_PER_DAY = Decimal("24")

ENTRY_SCHEMA = {
    "project_id": Field(kind="int", required=True, min_value=1),
    "work_date": Field(kind="date", required=True),
    "hours": Field(kind="decimal", required=True, min_value=0.25, max_value=24),
    "note": Field(kind="text", max_length=1000),
}
REVIEW_SCHEMA = {"review_note": Field(kind="text", max_length=1000)}


def _scope(user: dict, filters: Filters) -> Filters:
    """Employees see their own entries, managers their direct reports', admins all."""
    if user["role"] == EMPLOYEE:
        filters.eq("user_id", user["id"])
    elif user["role"] == MANAGER:
        filters.add("(user_manager_id = %s OR user_id = %s)", user["id"], user["id"])
    return filters


def _load(cur, user: dict, entry_id: int, lock: bool = False) -> dict:
    """Fetch a visible entry or raise 404."""
    if lock:
        model.lock_entry(cur, entry_id)
    row = model.find_entry(cur, _scope(user, Filters()).eq("id", entry_id))
    if row is None:
        raise not_found("Time entry")
    return row


def _check_entry(cur, user: dict, data: dict, exclude_id: int | None = None) -> None:
    """Hours must be quarter hours, not in the future, on a booked project, and <= 24 per day."""
    if data["hours"] % Decimal("0.25") != 0:
        raise bad_request("Validation failed", {"hours": "must be in quarter hours (0.25, 0.5, ...)"})
    if data["work_date"] > date.today():
        raise bad_request("Validation failed", {"work_date": "cannot be in the future"})
    if not model.is_booked_on(cur, user["id"], data["project_id"], data["work_date"]):
        raise bad_request("Validation failed",
                          {"project_id": "you are not booked on this project on that date"})
    logged = model.logged_hours_on(cur, user["id"], data["work_date"], exclude_id)
    if logged + data["hours"] > MAX_HOURS_PER_DAY:
        raise conflict(f"That would be more than 24 hours on {data['work_date'].isoformat()} "
                       f"({logged} h already logged)", {"logged_hours": logged})


def _can_review(user: dict, entry: dict) -> bool:
    """Admins review anyone's hours; managers their direct reports'."""
    if entry["user_id"] == user["id"]:
        return False
    return user["role"] == ADMIN or (user["role"] == MANAGER and entry["user_manager_id"] == user["id"])


def _label(entry: dict) -> str:
    """'7.5 h on PRJ-0001 on 2026-01-05' for audit summaries."""
    return f"{entry['hours']} h on {entry['project_code']} on {entry['work_date'].isoformat()}"


@router.get("/")
def list_entries(request: Request, cur) -> dict:
    """List time entries with filters (the "Hours to approve" screen uses status=pending)."""
    user, q = request.user, request.query
    filters = _scope(user, Filters())
    filters.eq("user_id", int_param(q, "user_id"))
    filters.eq("project_id", int_param(q, "project_id"))
    filters.eq("status", choice_param(q, "status", TIME_ENTRY_STATUSES))
    if choice_param(q, "reviewable", ("true", "false")) == "true":
        filters.add("status = 'pending' AND user_id <> %s", user["id"])
        if user["role"] == MANAGER:
            filters.eq("user_manager_id", user["id"])
    date_from = date_param(q, "from")
    if date_from:
        filters.add("work_date >= %s", date_from)
    date_to = date_param(q, "to")
    if date_to:
        filters.add("work_date <= %s", date_to)
    filters.search(["full_name", "employee_id", "project_name", "project_code", "note"], q.get("q"))
    result = model.list_entries(cur, filters, order_by(q, model.SORTS, "-work_date"), q)
    return view.entry_list(result, model.total_hours(cur, filters))


@router.get("/week")
def week(request: Request, cur) -> dict:
    """The caller's timesheet week (Monday-Sunday)."""
    user = request.user
    start = date_param(request.query, "start") or date.today()
    start = start - timedelta(days=start.weekday())
    end = start + timedelta(days=6)
    bookings = model.week_bookings(cur, user["id"], start, end)
    entries = model.week_entries(cur, user["id"], start, end)
    return view.week(start, end, bookings, entries)


@router.post("/")
def log_hours(request: Request, cur) -> dict:
    """Log hours on a project the employee is booked on."""
    user = request.user
    if user["role"] != EMPLOYEE:
        raise forbidden("Only employees log hours")
    data = validate(request.body, ENTRY_SCHEMA)
    model.lock_user(cur, user["id"])
    _check_entry(cur, user, data)
    entry = _load(cur, user, model.insert_entry(cur, user["id"], data))
    audit.record(cur, user, "time_entry", entry["id"], "create", f"logged {_label(entry)}", data)
    return view.entry(entry, 201)


@router.put("/{id}")
def update_entry(request: Request, cur) -> dict:
    """Edit a pending entry (owner only)."""
    user = request.user
    entry = _load(cur, user, request.params["id"], lock=True)
    if entry["user_id"] != user["id"]:
        raise forbidden("Only the person who logged the hours can edit them")
    if entry["status"] != "pending":
        raise conflict(f"Only pending entries can be edited; this one is {entry['status']}")
    changes = validate(request.body, ENTRY_SCHEMA, partial=True)
    if not changes:
        raise bad_request("Nothing to update")
    missing = {k: "is required" for k in ("project_id", "work_date", "hours") if k in changes and changes[k] is None}
    if missing:
        raise bad_request("Validation failed", missing)
    if "note" in changes and changes["note"] is None:
        changes["note"] = ""
    merged = {k: changes.get(k, entry[k]) for k in ("project_id", "work_date", "hours")}
    _check_entry(cur, user, merged, exclude_id=entry["id"])
    model.update_entry(cur, entry["id"], changes)
    updated = _load(cur, user, entry["id"])
    audit.record(cur, user, "time_entry", entry["id"], "update", f"changed logged hours to {_label(updated)}",
                 audit.diff(entry, changes))
    return view.entry(updated)


@router.post("/{id}/withdraw")
def withdraw(request: Request, cur) -> dict:
    """Withdraw a pending entry (owner only)."""
    user = request.user
    entry = _load(cur, user, request.params["id"], lock=True)
    if entry["user_id"] != user["id"]:
        raise forbidden("Only the person who logged the hours can withdraw them")
    if entry["status"] != "pending":
        raise conflict(f"Only pending entries can be withdrawn; this one is {entry['status']}")
    model.withdraw_entry(cur, entry["id"])
    audit.record(cur, user, "time_entry", entry["id"], "archive", f"withdrew {_label(entry)}")
    return view.entry(_load(cur, user, entry["id"]))


def _review(cur, user: dict, entry_id: int, approve: bool, note: str) -> dict:
    """Approve or reject one pending entry."""
    entry = _load(cur, user, entry_id, lock=True)
    if not _can_review(user, entry):
        raise forbidden("Managers approve their direct reports' hours; admins approve anyone's")
    if entry["status"] != "pending":
        raise conflict(f"Entry is already {entry['status']}")
    model.review_entry(cur, entry["id"], "approved" if approve else "rejected", user["id"], note)
    audit.record(cur, user, "time_entry", entry["id"], "update",
                 f"{'approved' if approve else 'rejected'} {entry['full_name']}'s {_label(entry)}",
                 {"status": {"from": "pending", "to": "approved" if approve else "rejected"}})
    return _load(cur, user, entry["id"])


@router.post("/approve-batch")
def approve_batch(request: Request, cur) -> dict:
    """Approve several pending entries at once."""
    user = request.user
    require_role(user, ADMIN, MANAGER)
    ids = request.body.get("ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        raise bad_request("Validation failed", {"ids": "must be a non-empty list of entry ids"})
    if len(ids) > 100:
        raise bad_request("Validation failed", {"ids": "at most 100 entries at a time"})
    return view.approved_batch([_review(cur, user, entry_id, True, "") for entry_id in sorted(set(ids))])


@router.post("/{id}/approve")
def approve(request: Request, cur) -> dict:
    """Approve one pending entry."""
    user = request.user
    note = validate(request.body, REVIEW_SCHEMA)["review_note"] or ""
    return view.entry(_review(cur, user, request.params["id"], True, note))


@router.post("/{id}/reject")
def reject(request: Request, cur) -> dict:
    """Reject one pending entry with a reason."""
    user = request.user
    note = validate(request.body, REVIEW_SCHEMA)["review_note"]
    if not note:
        raise bad_request("Validation failed", {"review_note": "is required when rejecting"})
    return view.entry(_review(cur, user, request.params["id"], False, note))
