"""
Assignments MODEL: every database query for bookings.

Only this file talks to the ``project_assignments`` table for the assignments
service. The controller calls these functions; nothing here knows about HTTP.
"""

from shared.projects import PLANNED_COST_SQL
from shared.query import Filters, paginated

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

GRID_PEOPLE_SELECT = (
    "SELECT id, employee_id, first_name || ' ' || last_name AS full_name, job_title, role, is_active "
    "FROM users"
)
GRID_PEOPLE_SORTS = {"full_name": "full_name"}
BOOKED_BETWEEN_SQL = """id IN (SELECT a.user_id FROM project_assignments a JOIN projects p ON p.id = a.project_id
                      WHERE NOT a.is_archived AND NOT p.is_archived AND a.start_date <= %s AND a.end_date >= %s)"""


def list_assignments(cur, filters: Filters, order_sql: str, query: dict) -> dict:
    """One page of assignments matching the filters."""
    return paginated(cur, SELECT, filters, order_sql, query)


def find_assignment(cur, filters: Filters) -> dict | None:
    """The first assignment matching the (scoped) filters, or None."""
    cur.execute(f"SELECT * FROM ({SELECT}) AS t {filters.where()}", filters.params)  # nosec B608
    return cur.fetchone()


def list_grid_people(cur, filters: Filters, order_sql: str, query: dict) -> dict:
    """One page of people for the allocation grid."""
    return paginated(cur, GRID_PEOPLE_SELECT, filters, order_sql, query)


def grid_bookings(cur, user_ids: list[int], start, end, see_all: bool, viewer_id: int) -> list[dict]:
    """Live bookings of these people overlapping the range, flagged when the viewer may see the project."""
    cur.execute(
        """
        SELECT a.user_id, a.project_id, p.code, p.name, a.hours_per_week, a.start_date, a.end_date,
               (%s OR p.manager_id = %s) AS visible
        FROM project_assignments a JOIN projects p ON p.id = a.project_id
        WHERE a.user_id = ANY(%s::int[]) AND NOT a.is_archived AND NOT p.is_archived
          AND a.start_date <= %s AND a.end_date >= %s
        """,
        [see_all, viewer_id, user_ids, end, start],
    )
    return cur.fetchall()


def insert_assignment(cur, project_id: int, user_id: int, data: dict, assigned_by: int) -> int:
    """Insert a booking and return the new id."""
    cur.execute(
        """
        INSERT INTO project_assignments (project_id, user_id, project_role, hours_per_week,
                                         start_date, end_date, assigned_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        [project_id, user_id, data["project_role"] or "", data["hours_per_week"],
         data["start_date"], data["end_date"], assigned_by],
    )
    return cur.fetchone()["id"]


def update_assignment(cur, assignment_id: int, data: dict) -> None:
    """Update the given columns of a booking (column names come from a validated schema)."""
    assignments = ", ".join(f"{name} = %s" for name in data)
    cur.execute(f"UPDATE project_assignments SET {assignments}, updated_at = now() WHERE id = %s",  # nosec B608
                [*data.values(), assignment_id])


def archive_assignment(cur, assignment_id: int) -> None:
    """Mark a booking archived."""
    cur.execute("UPDATE project_assignments SET is_archived = TRUE, archived_at = now(), updated_at = now() "
                "WHERE id = %s", [assignment_id])


def reactivate_assignment(cur, assignment_id: int) -> None:
    """Clear a booking's archived flag."""
    cur.execute("UPDATE project_assignments SET is_archived = FALSE, archived_at = NULL, updated_at = now() "
                "WHERE id = %s", [assignment_id])
