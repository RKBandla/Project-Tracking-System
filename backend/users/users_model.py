"""
Users MODEL: every database query for people.

Only this file talks to the ``users`` table for the users service. The
controller calls these functions; nothing here knows about HTTP.
"""

from shared.query import Filters, paginated
from shared.users import get_user, next_employee_id  # lookups shared with other services

__all__ = ["get_user", "next_employee_id", "list_users", "insert_user", "update_user", "set_password_hash",
           "would_create_reporting_cycle", "count_reports_and_projects", "active_assignments"]

LIST_SELECT = """
    SELECT u.id, u.employee_id, u.first_name, u.last_name,
           u.first_name || ' ' || u.last_name AS full_name,
           u.email, u.job_title, u.salary_cents, u.role, u.manager_id, u.is_active,
           u.created_at, u.updated_at,
           CASE WHEN m.id IS NULL THEN NULL ELSE m.first_name || ' ' || m.last_name END AS manager_name,
           (SELECT COALESCE(SUM(a.hours_per_week), 0) FROM project_assignments a
              JOIN projects p ON p.id = a.project_id
             WHERE a.user_id = u.id AND NOT a.is_archived AND NOT p.is_archived
               AND CURRENT_DATE BETWEEN a.start_date AND a.end_date)::int AS current_week_hours
    FROM users u
    LEFT JOIN users m ON m.id = u.manager_id
"""
SORTS = {
    "name": "last_name", "first_name": "first_name", "employee_id": "employee_id",
    "email": "email", "role": "role", "job_title": "job_title",
    "current_week_hours": "current_week_hours", "created_at": "created_at",
}


def list_users(cur, filters: Filters, order_sql: str, query: dict) -> dict:
    """One page of the people directory, with this week's booked hours."""
    return paginated(cur, LIST_SELECT, filters, order_sql, query)


def insert_user(cur, data: dict, employee_id: str, password_hash: str) -> int:
    """Insert a user and return the new id."""
    cur.execute(
        """
        INSERT INTO users (employee_id, first_name, last_name, email, job_title, salary_cents,
                           role, manager_id, password_hash)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        [employee_id, data["first_name"], data["last_name"], data["email"], data["job_title"],
         data["salary_cents"], data["role"], data["manager_id"], password_hash],
    )
    return cur.fetchone()["id"]


def update_user(cur, user_id: int, data: dict) -> None:
    """Update the given columns of a user (column names come from a validated schema)."""
    assignments = ", ".join(f"{name} = %s" for name in data)
    cur.execute(f"UPDATE users SET {assignments}, updated_at = now() WHERE id = %s",  # nosec B608
                [*data.values(), user_id])


def set_password_hash(cur, user_id: int, password_hash: str) -> None:
    """Replace a user's password hash."""
    cur.execute("UPDATE users SET password_hash = %s, updated_at = now() WHERE id = %s",
                [password_hash, user_id])


def would_create_reporting_cycle(cur, manager_id: int, user_id: int) -> bool:
    """True if ``user_id`` is already above ``manager_id`` in the reporting line."""
    cur.execute(
        """
        WITH RECURSIVE chain AS (
            SELECT id, manager_id FROM users WHERE id = %s
            UNION
            SELECT u.id, u.manager_id FROM users u JOIN chain c ON u.id = c.manager_id
        )
        SELECT 1 FROM chain WHERE id = %s
        """,
        [manager_id, user_id],
    )
    return cur.fetchone() is not None


def count_reports_and_projects(cur, user_id: int) -> tuple[int, int]:
    """Active direct reports and non-archived managed projects of a user."""
    cur.execute("SELECT count(*) AS n FROM users WHERE manager_id = %s AND is_active", [user_id])
    reports = cur.fetchone()["n"]
    cur.execute("SELECT count(*) AS n FROM projects WHERE manager_id = %s AND NOT is_archived", [user_id])
    return reports, cur.fetchone()["n"]


def active_assignments(cur, user_id: int, start) -> list[dict]:
    """A person's bookings that haven't ended, on non-archived projects."""
    cur.execute(
        """
        SELECT a.id, a.project_id, p.code AS project_code, p.name AS project_name,
               a.project_role, a.hours_per_week, a.start_date, a.end_date
        FROM project_assignments a JOIN projects p ON p.id = a.project_id
        WHERE a.user_id = %s AND NOT a.is_archived AND NOT p.is_archived AND a.end_date >= %s
        ORDER BY a.start_date, p.name
        """,
        [user_id, start],
    )
    return cur.fetchall()
