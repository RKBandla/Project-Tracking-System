"""
Timesheets MODEL: every database query for logged hours.

Only this file talks to the ``time_entries`` table for the timesheets
service. The controller calls these functions; nothing here knows about HTTP.
"""

from decimal import Decimal

from shared.query import Filters, paginated

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


def lock_entry(cur, entry_id: int) -> None:
    """Lock a time entry row for the rest of the transaction."""
    cur.execute("SELECT id FROM time_entries WHERE id = %s FOR UPDATE", [entry_id])


def find_entry(cur, filters: Filters) -> dict | None:
    """The one entry matching the filters (already scoped to the viewer), or None."""
    cur.execute(f"SELECT * FROM ({SELECT}) AS x {filters.where()}", filters.params)  # nosec B608
    return cur.fetchone()


def list_entries(cur, filters: Filters, order_sql: str, query: dict) -> dict:
    """One page of time entries."""
    return paginated(cur, SELECT, filters, order_sql, query)


def total_hours(cur, filters: Filters) -> Decimal:
    """Sum of hours of every entry matching the filters (all pages)."""
    cur.execute(f"SELECT COALESCE(SUM(hours), 0) AS hours FROM ({SELECT}) AS x {filters.where()}",  # nosec B608
                filters.params)
    return cur.fetchone()["hours"]


def is_booked_on(cur, user_id: int, project_id: int, work_date) -> bool:
    """True if the person has an active booking on the project covering that date."""
    cur.execute(
        """SELECT 1 FROM project_assignments a JOIN projects p ON p.id = a.project_id
           WHERE a.user_id = %s AND a.project_id = %s AND NOT a.is_archived AND NOT p.is_archived
             AND %s BETWEEN a.start_date AND a.end_date""",
        [user_id, project_id, work_date],
    )
    return bool(cur.fetchone())


def logged_hours_on(cur, user_id: int, work_date, exclude_id: int | None = None) -> Decimal:
    """Pending and approved hours a person logged on one day, ignoring one entry."""
    cur.execute(
        """SELECT COALESCE(SUM(hours), 0) AS hours FROM time_entries
           WHERE user_id = %s AND work_date = %s AND status IN ('pending', 'approved')
             AND id IS DISTINCT FROM %s""",
        [user_id, work_date, exclude_id],
    )
    return cur.fetchone()["hours"]


def lock_user(cur, user_id: int) -> None:
    """Lock a user row so concurrent logs for the same person run one at a time."""
    cur.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", [user_id])


def insert_entry(cur, user_id: int, data: dict) -> int:
    """Insert a pending time entry and return the new id."""
    cur.execute(
        "INSERT INTO time_entries (user_id, project_id, work_date, hours, note) VALUES (%s, %s, %s, %s, %s) "
        "RETURNING id",
        [user_id, data["project_id"], data["work_date"], data["hours"], data["note"] or ""],
    )
    return cur.fetchone()["id"]


def update_entry(cur, entry_id: int, changes: dict) -> None:
    """Update the given columns of an entry (column names come from a validated schema)."""
    assignments = ", ".join(f"{name} = %s" for name in changes)
    cur.execute(f"UPDATE time_entries SET {assignments}, updated_at = now() WHERE id = %s",  # nosec B608
                [*changes.values(), entry_id])


def withdraw_entry(cur, entry_id: int) -> None:
    """Mark an entry withdrawn."""
    cur.execute("UPDATE time_entries SET status = 'withdrawn', updated_at = now() WHERE id = %s", [entry_id])


def review_entry(cur, entry_id: int, status: str, reviewer_id: int, note: str) -> None:
    """Record an approval or rejection on an entry."""
    cur.execute(
        "UPDATE time_entries SET status = %s, reviewed_by = %s, reviewed_at = now(), review_note = %s, "
        "updated_at = now() WHERE id = %s",
        [status, reviewer_id, note, entry_id],
    )


def week_bookings(cur, user_id: int, start, end) -> list[dict]:
    """A person's active bookings that overlap the week."""
    cur.execute(
        """SELECT a.project_id, p.code AS project_code, p.name AS project_name, a.project_role,
                  a.hours_per_week, a.start_date, a.end_date
           FROM project_assignments a JOIN projects p ON p.id = a.project_id
           WHERE a.user_id = %s AND NOT a.is_archived AND NOT p.is_archived
             AND a.start_date <= %s AND a.end_date >= %s
           ORDER BY p.name""",
        [user_id, end, start],
    )
    return cur.fetchall()


def week_entries(cur, user_id: int, start, end) -> list[dict]:
    """A person's time entries (any status) dated within the week."""
    cur.execute(SELECT + " WHERE t.user_id = %s AND t.work_date BETWEEN %s AND %s ORDER BY t.work_date, t.id",
                [user_id, start, end])
    return cur.fetchall()
