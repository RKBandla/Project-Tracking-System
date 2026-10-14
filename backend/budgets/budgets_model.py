"""
Budgets MODEL: every database query for project budgets.

Budgets live on the ``projects`` table; the planned and consumed cost formulas
and the project lookups are shared with the projects service. The controller
calls these functions; nothing here knows about HTTP.
"""

from shared.projects import CONSUMED_COST_SQL, PLANNED_COST_SQL, PROJECT_SELECT, get_project
from shared.query import Filters, paginated

__all__ = ["get_project", "list_projects", "planned_by_person", "consumed_by_person", "consumed_by_month",
           "set_budget"]

SORTS = {"name": "name", "code": "code", "budget_cents": "budget_cents", "planned_cents": "planned_cents",
         "consumed_cents": "consumed_cents", "end_date": "end_date"}


def list_projects(cur, filters: Filters, order_sql: str, query: dict) -> dict:
    """One page of projects with their budget, planned and consumed cost."""
    return paginated(cur, PROJECT_SELECT, filters, order_sql, query)


def planned_by_person(cur, project_id: int) -> list[dict]:
    """Planned cost and hours of a project per assigned person."""
    cur.execute(
        f"""SELECT u.id AS user_id, u.first_name || ' ' || u.last_name AS full_name, u.job_title,
                   SUM({PLANNED_COST_SQL})::bigint AS planned_cents,
                   SUM(a.hours_per_week * ((a.end_date - a.start_date + 1) / 7.0))::numeric(10,1) AS planned_hours
            FROM project_assignments a JOIN users u ON u.id = a.user_id
            WHERE a.project_id = %s AND NOT a.is_archived
            GROUP BY u.id ORDER BY full_name""",  # nosec B608 - constant SQL fragments
        [project_id],
    )
    return cur.fetchall()


def consumed_by_person(cur, project_id: int) -> list[dict]:
    """Consumed cost and approved hours of a project per person who logged time."""
    cur.execute(
        f"""SELECT u.id AS user_id, u.first_name || ' ' || u.last_name AS full_name, u.job_title,
                   SUM({CONSUMED_COST_SQL})::bigint AS consumed_cents, SUM(t.hours) AS approved_hours
            FROM time_entries t JOIN users u ON u.id = t.user_id
            WHERE t.project_id = %s AND t.status = 'approved'
            GROUP BY u.id""",  # nosec B608
        [project_id],
    )
    return cur.fetchall()


def consumed_by_month(cur, project_id: int) -> list[dict]:
    """Consumed cost and approved hours of a project per calendar month."""
    cur.execute(
        f"""SELECT date_trunc('month', t.work_date)::date AS month,
                   SUM({CONSUMED_COST_SQL})::bigint AS consumed_cents, SUM(t.hours) AS hours
            FROM time_entries t JOIN users u ON u.id = t.user_id
            WHERE t.project_id = %s AND t.status = 'approved'
            GROUP BY 1 ORDER BY 1""",  # nosec B608
        [project_id],
    )
    return cur.fetchall()


def set_budget(cur, project_id: int, budget_cents: int) -> None:
    """Replace a project's budget."""
    cur.execute("UPDATE projects SET budget_cents = %s, updated_at = now() WHERE id = %s",
                [budget_cents, project_id])
