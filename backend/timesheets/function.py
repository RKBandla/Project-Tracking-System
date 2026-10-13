"""
Timesheets service: employees log hours, managers and admins approve them.

Routes (relative to /api/timesheets):
    GET  /                  list entries (employee: own; manager: direct reports; admin: all)
    GET  /week              the caller's week: bookable projects, entries, daily totals (?start=)
    POST /                  log hours {project_id, work_date, hours, note} (employees)
    PUT  /{id}              edit a pending entry (owner)
    POST /{id}/withdraw     withdraw a pending entry (owner) - nothing is deleted
    POST /{id}/approve      approve (admin: anyone; manager: direct reports)
    POST /{id}/reject       reject with a reason
    POST /approve-batch     approve several pending entries {ids: [...]}

Only approved hours count towards a project's consumed cost.
"""

from datetime import date, timedelta
from decimal import Decimal

from shared import audit
from shared.app import make_handler
from shared.errors import bad_request, conflict, forbidden, not_found
from shared.http import Request, Router, response
from shared.query import Filters, choice_param, date_param, int_param, order_by, paginated
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

SELECT = """
    SELECT t.*, p.code AS project_code, p.name AS project_name,
           u.employee_id, u.first_name || ' ' || u.last_name AS full_name, u.manager_id AS user_manager_id,
           CASE WHEN r.id IS NULL THEN NULL ELSE r.first_name || ' ' || r.last_name END AS reviewed_by_name
    FROM time_entries t
    JOIN projects p ON p.id = t.project_id
    JOIN users u ON u.id = t.user_id
    LEFT JOIN users r ON r.id = t.reviewed_by
"""
SORTS = {"work_date": "work_date", "hours": "hours", "status": "status", "full_name": "full_name",
         "project_name": "project_name", "created_at": "created_at"}


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
        cur.execute("SELECT id FROM time_entries WHERE id = %s FOR UPDATE", [entry_id])
    filters = _scope(user, Filters()).eq("id", entry_id)
    cur.execute(f"SELECT * FROM ({SELECT}) AS x {filters.where()}", filters.params)  # nosec B608
    row = cur.fetchone()
    if row is None:
        raise not_found("Time entry")
    return row


def _check_entry(cur, user: dict, data: dict, exclude_id: int | None = None) -> None:
    """Hours must be quarter hours, not in the future, on a booked project, and <= 24 per day."""
    if data["hours"] % Decimal("0.25") != 0:
        raise bad_request("Validation failed", {"hours": "must be in quarter hours (0.25, 0.5, ...)"})
    if data["work_date"] > date.today():
        raise bad_request("Validation failed", {"work_date": "cannot be in the future"})
    cur.execute(
        """SELECT 1 FROM project_assignments a JOIN projects p ON p.id = a.project_id
           WHERE a.user_id = %s AND a.project_id = %s AND NOT a.is_archived AND NOT p.is_archived
             AND %s BETWEEN a.start_date AND a.end_date""",
        [user["id"], data["project_id"], data["work_date"]],
    )
    if not cur.fetchone():
        raise bad_request("Validation failed",
                          {"project_id": "you are not booked on this project on that date"})
    cur.execute(
        """SELECT COALESCE(SUM(hours), 0) AS hours FROM time_entries
           WHERE user_id = %s AND work_date = %s AND status IN ('pending', 'approved')
             AND id IS DISTINCT FROM %s""",
        [user["id"], data["work_date"], exclude_id],
    )
    logged = cur.fetchone()["hours"]
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
    result = paginated(cur, SELECT, filters, order_by(q, SORTS, "-work_date"), q)
    cur.execute(f"SELECT COALESCE(SUM(hours), 0) AS hours FROM ({SELECT}) AS x {filters.where()}",  # nosec B608
                filters.params)
    result["total_hours"] = cur.fetchone()["hours"]
    return response(200, result)


@router.get("/week")
def week(request: Request, cur) -> dict:
    """The caller's timesheet week (Monday-Sunday)."""
    user = request.user
    start = date_param(request.query, "start") or date.today()
    start = start - timedelta(days=start.weekday())
    end = start + timedelta(days=6)
    cur.execute(
        """SELECT a.project_id, p.code AS project_code, p.name AS project_name, a.project_role,
                  a.hours_per_week, a.start_date, a.end_date
           FROM project_assignments a JOIN projects p ON p.id = a.project_id
           WHERE a.user_id = %s AND NOT a.is_archived AND NOT p.is_archived
             AND a.start_date <= %s AND a.end_date >= %s
           ORDER BY p.name""",
        [user["id"], end, start],
    )
    bookings = cur.fetchall()
    cur.execute(SELECT + " WHERE t.user_id = %s AND t.work_date BETWEEN %s AND %s ORDER BY t.work_date, t.id",
                [user["id"], start, end])
    entries = cur.fetchall()
    days = []
    for i in range(7):
        day = start + timedelta(days=i)
        counted = [e for e in entries if e["work_date"] == day and e["status"] in ("pending", "approved")]
        days.append({"date": day, "hours": sum((e["hours"] for e in counted), Decimal(0))})
    counted = [e for e in entries if e["status"] in ("pending", "approved")]
    return response(200, {
        "week_start": start,
        "week_end": end,
        "bookings": bookings,
        "entries": entries,
        "days": days,
        "booked_hours": sum(b["hours_per_week"] for b in bookings),
        "logged_hours": sum((e["hours"] for e in counted), Decimal(0)),
        "approved_hours": sum((e["hours"] for e in entries if e["status"] == "approved"), Decimal(0)),
    })


@router.post("/")
def log_hours(request: Request, cur) -> dict:
    """Log hours on a project the employee is booked on."""
    user = request.user
    if user["role"] != EMPLOYEE:
        raise forbidden("Only employees log hours")
    data = validate(request.body, ENTRY_SCHEMA)
    cur.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", [user["id"]])
    _check_entry(cur, user, data)
    cur.execute(
        "INSERT INTO time_entries (user_id, project_id, work_date, hours, note) VALUES (%s, %s, %s, %s, %s) "
        "RETURNING id",
        [user["id"], data["project_id"], data["work_date"], data["hours"], data["note"] or ""],
    )
    entry = _load(cur, user, cur.fetchone()["id"])
    audit.record(cur, user, "time_entry", entry["id"], "create", f"logged {_label(entry)}", data)
    return response(201, entry)


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
    assignments = ", ".join(f"{name} = %s" for name in changes)
    cur.execute(f"UPDATE time_entries SET {assignments}, updated_at = now() WHERE id = %s",  # nosec B608
                [*changes.values(), entry["id"]])
    updated = _load(cur, user, entry["id"])
    audit.record(cur, user, "time_entry", entry["id"], "update", f"changed logged hours to {_label(updated)}",
                 audit.diff(entry, changes))
    return response(200, updated)


@router.post("/{id}/withdraw")
def withdraw(request: Request, cur) -> dict:
    """Withdraw a pending entry (owner only)."""
    user = request.user
    entry = _load(cur, user, request.params["id"], lock=True)
    if entry["user_id"] != user["id"]:
        raise forbidden("Only the person who logged the hours can withdraw them")
    if entry["status"] != "pending":
        raise conflict(f"Only pending entries can be withdrawn; this one is {entry['status']}")
    cur.execute("UPDATE time_entries SET status = 'withdrawn', updated_at = now() WHERE id = %s", [entry["id"]])
    audit.record(cur, user, "time_entry", entry["id"], "archive", f"withdrew {_label(entry)}")
    return response(200, _load(cur, user, entry["id"]))


def _review(cur, user: dict, entry_id: int, approve: bool, note: str) -> dict:
    """Approve or reject one pending entry."""
    entry = _load(cur, user, entry_id, lock=True)
    if not _can_review(user, entry):
        raise forbidden("Managers approve their direct reports' hours; admins approve anyone's")
    if entry["status"] != "pending":
        raise conflict(f"Entry is already {entry['status']}")
    cur.execute(
        "UPDATE time_entries SET status = %s, reviewed_by = %s, reviewed_at = now(), review_note = %s, "
        "updated_at = now() WHERE id = %s",
        ["approved" if approve else "rejected", user["id"], note, entry["id"]],
    )
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
    approved = [_review(cur, user, entry_id, True, "") for entry_id in sorted(set(ids))]
    return response(200, {"approved": approved})


@router.post("/{id}/approve")
def approve(request: Request, cur) -> dict:
    """Approve one pending entry."""
    user = request.user
    note = validate(request.body, REVIEW_SCHEMA)["review_note"] or ""
    return response(200, _review(cur, user, request.params["id"], True, note))


@router.post("/{id}/reject")
def reject(request: Request, cur) -> dict:
    """Reject one pending entry with a reason."""
    user = request.user
    note = validate(request.body, REVIEW_SCHEMA)["review_note"]
    if not note:
        raise bad_request("Validation failed", {"review_note": "is required when rejecting"})
    return response(200, _review(cur, user, request.params["id"], False, note))


handler = make_handler(router, "timesheets")
