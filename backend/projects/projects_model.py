"""
Projects MODEL: every database query for projects and the dashboard.

Only this file runs SQL for the projects service. The controller calls these
functions; nothing here knows about HTTP.
"""

from shared.projects import PROJECT_SELECT, get_project, insert_project  # get/insert shared with other services
from shared.query import Filters, paginated
from shared.users import get_user  # lookup shared with other services

__all__ = ["get_user", "get_project", "insert_project", "today", "list_projects", "dashboard_projects",
           "deliverable_scope", "upcoming_deliverables", "overdue_deliverable_count", "upcoming_milestones",
           "unread_notification_count", "fully_booked_people", "pending_request_count", "pending_hours_count",
           "active_assignments", "logged_this_week", "update_project", "archive_project", "reactivate_project",
           "team_bookings", "deliverable_counts", "team_members"]

SORTS = {
    "name": "name", "code": "code", "status": "status", "start_date": "start_date",
    "end_date": "end_date", "budget_cents": "budget_cents", "consumed_cents": "consumed_cents",
    "created_at": "created_at", "updated_at": "updated_at", "manager_name": "manager_name",
}


def today(cur):
    """The database's current date (keeps 'today' consistent with SQL comparisons)."""
    cur.execute("SELECT CURRENT_DATE AS d")
    return cur.fetchone()["d"]


def list_projects(cur, filters: Filters, order_sql: str, query: dict) -> dict:
    """One page of projects with their metrics (rows not yet presented)."""
    return paginated(cur, PROJECT_SELECT, filters, order_sql, query)


def dashboard_projects(cur, where: str, params: list) -> list[dict]:
    """Projects in scope, at-risk first, then by end date and name."""
    cur.execute(
        f"SELECT * FROM ({PROJECT_SELECT}) AS pr {where} "  # nosec B608
        "ORDER BY at_risk DESC, end_date NULLS LAST, name",
        params,
    )
    return cur.fetchall()


def deliverable_scope(where: str, params: list, assignee_id: int | None = None) -> tuple[str, list]:
    """SQL condition (alias d) for open deliverables of projects in scope, optionally only one assignee's."""
    scope = f"d.project_id IN (SELECT id FROM projects {where}) AND NOT d.is_archived"  # nosec B608
    scope_params = list(params)
    if assignee_id is not None:
        scope += " AND d.assignee_id = %s"
        scope_params.append(assignee_id)
    return scope, scope_params


def upcoming_deliverables(cur, scope: str, params: list) -> list[dict]:
    """Up to 10 unfinished deliverables due within the next 14 days (or already due)."""
    cur.execute(
        f"""SELECT d.id, d.title, d.status, d.due_date, d.progress_pct, d.project_id,
                   p.code AS project_code, p.name AS project_name
            FROM deliverables d JOIN projects p ON p.id = d.project_id
            WHERE {scope} AND d.status <> 'done' AND d.due_date IS NOT NULL
              AND d.due_date <= CURRENT_DATE + 14
            ORDER BY d.due_date LIMIT 10""",  # nosec B608
        params,
    )
    return cur.fetchall()


def overdue_deliverable_count(cur, scope: str, params: list) -> int:
    """Number of unfinished deliverables past their due date."""
    cur.execute(
        f"""SELECT count(*) AS n FROM deliverables d WHERE {scope}
            AND d.status <> 'done' AND d.due_date < CURRENT_DATE""",  # nosec B608
        params,
    )
    return cur.fetchone()["n"]


def upcoming_milestones(cur, where: str, params: list) -> list[dict]:
    """Open milestones in the next 90 days, plus any already missed, on the projects in scope."""
    cur.execute(
        f"""SELECT d.id, d.title, d.status, d.due_date, d.project_id, p.code AS project_code,
                   p.name AS project_name, d.due_date < CURRENT_DATE AS is_missed
            FROM deliverables d JOIN projects p ON p.id = d.project_id
            WHERE d.project_id IN (SELECT id FROM projects {where}) AND NOT d.is_archived AND d.is_milestone
              AND d.status <> 'done' AND d.due_date <= CURRENT_DATE + 90
            ORDER BY d.due_date LIMIT 8""",  # nosec B608
        params,
    )
    return cur.fetchall()


def unread_notification_count(cur, user_id: int) -> int:
    """Number of unread notifications of a user."""
    cur.execute("SELECT count(*) AS n FROM notifications WHERE user_id = %s AND read_at IS NULL", [user_id])
    return cur.fetchone()["n"]


def fully_booked_people(cur, max_hours: int) -> list[dict]:
    """People booked to the weekly limit in any of the next 8 weeks."""
    cur.execute(
        """
        WITH weeks AS (
            SELECT generate_series(date_trunc('week', CURRENT_DATE),
                                   date_trunc('week', CURRENT_DATE) + interval '7 weeks',
                                   interval '1 week')::date AS week_start
        ), load AS (
            SELECT a.user_id, w.week_start, SUM(a.hours_per_week) AS hours
            FROM weeks w
            JOIN project_assignments a ON NOT a.is_archived
                 AND a.start_date <= w.week_start + 6 AND a.end_date >= w.week_start
            JOIN projects p ON p.id = a.project_id AND NOT p.is_archived
            GROUP BY a.user_id, w.week_start
        )
        SELECT u.id, u.first_name || ' ' || u.last_name AS full_name, u.job_title,
               MAX(l.hours)::int AS peak_hours
        FROM load l JOIN users u ON u.id = l.user_id
        GROUP BY u.id HAVING MAX(l.hours) >= %s
        ORDER BY full_name LIMIT 20
        """,
        [max_hours],
    )
    return cur.fetchall()


def pending_request_count(cur, requested_by: int | None = None) -> int:
    """Pending project requests: all of them, or only those of one requester."""
    if requested_by is None:
        cur.execute("SELECT count(*) AS n FROM project_requests WHERE status = 'pending'")
    else:
        cur.execute("SELECT count(*) AS n FROM project_requests WHERE status = 'pending' AND requested_by = %s",
                    [requested_by])
    return cur.fetchone()["n"]


def pending_hours_count(cur, manager_id: int | None = None) -> int:
    """Pending time entries: all of them, or only those of one manager's direct reports."""
    if manager_id is None:
        cur.execute("SELECT count(*) AS n FROM time_entries WHERE status = 'pending'")
    else:
        cur.execute(
            "SELECT count(*) AS n FROM time_entries t JOIN users u ON u.id = t.user_id "
            "WHERE t.status = 'pending' AND u.manager_id = %s",
            [manager_id],
        )
    return cur.fetchone()["n"]


def active_assignments(cur, user_id: int, start) -> list[dict]:
    """A person's bookings that haven't ended, on non-archived projects."""
    cur.execute(
        """SELECT a.id, a.project_id, p.code AS project_code, p.name AS project_name,
                  a.project_role, a.hours_per_week, a.start_date, a.end_date
           FROM project_assignments a JOIN projects p ON p.id = a.project_id
           WHERE a.user_id = %s AND NOT a.is_archived AND NOT p.is_archived AND a.end_date >= %s
           ORDER BY a.start_date, p.name""",
        [user_id, start],
    )
    return cur.fetchall()


def logged_this_week(cur, user_id: int) -> dict:
    """Pending and approved hours a person has logged since the start of this week."""
    cur.execute(
        """SELECT COALESCE(SUM(hours) FILTER (WHERE status = 'pending'), 0) AS pending,
                  COALESCE(SUM(hours) FILTER (WHERE status = 'approved'), 0) AS approved
           FROM time_entries WHERE user_id = %s AND work_date >= date_trunc('week', CURRENT_DATE)""",
        [user_id],
    )
    return cur.fetchone()


def update_project(cur, project_id: int, data: dict) -> None:
    """Update the given columns of a project (column names come from a validated schema)."""
    assignments = ", ".join(f"{name} = %s" for name in data)
    cur.execute(f"UPDATE projects SET {assignments}, updated_at = now() WHERE id = %s",  # nosec B608
                [*data.values(), project_id])


def archive_project(cur, project_id: int, user_id: int) -> None:
    """Mark a project archived by a user."""
    cur.execute(
        "UPDATE projects SET is_archived = TRUE, archived_at = now(), archived_by = %s, updated_at = now() "
        "WHERE id = %s",
        [user_id, project_id],
    )


def reactivate_project(cur, project_id: int) -> None:
    """Clear a project's archived state."""
    cur.execute(
        "UPDATE projects SET is_archived = FALSE, archived_at = NULL, archived_by = NULL, updated_at = now() "
        "WHERE id = %s",
        [project_id],
    )


def team_bookings(cur, project_id: int) -> list[dict]:
    """Per person on a project: earliest start and latest end of their non-archived bookings."""
    cur.execute(
        """SELECT user_id, MIN(start_date) AS start_date, MAX(end_date) AS end_date
           FROM project_assignments WHERE project_id = %s AND NOT is_archived
           GROUP BY user_id ORDER BY user_id""",
        [project_id],
    )
    return cur.fetchall()


def deliverable_counts(cur, project_id: int) -> dict:
    """Non-archived deliverables of a project counted by status, plus overdue."""
    cur.execute(
        """SELECT count(*) AS total,
                  count(*) FILTER (WHERE status = 'todo') AS todo,
                  count(*) FILTER (WHERE status = 'in_progress') AS in_progress,
                  count(*) FILTER (WHERE status = 'blocked') AS blocked,
                  count(*) FILTER (WHERE status = 'done') AS done,
                  count(*) FILTER (WHERE status <> 'done' AND due_date < CURRENT_DATE) AS overdue
           FROM deliverables WHERE project_id = %s AND NOT is_archived""",
        [project_id],
    )
    return cur.fetchone()


def team_members(cur, project_id: int) -> list[dict]:
    """A project's non-archived bookings with the people's names and job titles."""
    cur.execute(
        """SELECT a.id, a.user_id, u.employee_id, u.first_name || ' ' || u.last_name AS full_name,
                  u.job_title, a.project_role, a.hours_per_week, a.start_date, a.end_date
           FROM project_assignments a JOIN users u ON u.id = a.user_id
           WHERE a.project_id = %s AND NOT a.is_archived ORDER BY u.last_name, a.start_date""",
        [project_id],
    )
    return cur.fetchall()
