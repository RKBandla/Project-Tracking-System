"""
Deliverables MODEL: every database query for deliverables and their dependencies.

Only this file talks to the ``deliverables`` and ``deliverable_dependencies``
tables for the deliverables service. The controller calls these functions;
nothing here knows about HTTP.
"""

from shared.query import Filters, paginated
from shared.rbac import load_managed_project, load_visible_project, visible_project_ids  # shared lookups

__all__ = ["load_managed_project", "load_visible_project", "scoped_filters", "get_deliverable",
           "list_deliverables", "project_graph_nodes", "is_assigned_to_project", "active_ids_on_project",
           "find_dependency_loop", "titles_by_id", "set_dependencies", "open_dependencies", "insert_deliverable",
           "update_deliverable", "archive_deliverable", "restore_deliverable"]

SELECT = """
    SELECT d.*, p.code AS project_code, p.name AS project_name, p.is_archived AS project_is_archived,
           CASE WHEN u.id IS NULL THEN NULL ELSE u.first_name || ' ' || u.last_name END AS assignee_name,
           (NOT d.is_archived AND d.status <> 'done' AND d.due_date < CURRENT_DATE) AS is_overdue,
           COALESCE((SELECT array_agg(dd.depends_on_id ORDER BY dd.depends_on_id)
                       FROM deliverable_dependencies dd
                      WHERE dd.deliverable_id = d.id AND dd.archived_at IS NULL), '{}') AS depends_on,
           EXISTS (SELECT 1 FROM deliverable_dependencies dd JOIN deliverables x ON x.id = dd.depends_on_id
                    WHERE dd.deliverable_id = d.id AND dd.archived_at IS NULL
                      AND NOT x.is_archived AND x.status <> 'done') AS is_blocked
    FROM deliverables d
    JOIN projects p ON p.id = d.project_id
    LEFT JOIN users u ON u.id = d.assignee_id
"""
SORTS = {"due_date": "due_date", "start_date": "start_date", "title": "title", "status": "status",
         "progress_pct": "progress_pct", "created_at": "created_at", "updated_at": "updated_at",
         "project_name": "project_name"}


def scoped_filters(user: dict) -> Filters:
    """Filters restricted to deliverables on projects the user may view."""
    filters = Filters()
    visible = visible_project_ids(user)
    if visible is not None:
        sql, params = visible
        filters.add(f"project_id IN ({sql})", *params)
    return filters


def get_deliverable(cur, user: dict, deliverable_id: int) -> dict | None:
    """One deliverable the user may view, or None."""
    filters = scoped_filters(user).eq("id", deliverable_id)
    cur.execute(f"SELECT * FROM ({SELECT}) AS t {filters.where()}", filters.params)  # nosec B608
    return cur.fetchone()


def list_deliverables(cur, filters: Filters, order_sql: str, query: dict) -> dict:
    """One page of deliverables."""
    return paginated(cur, SELECT, filters, order_sql, query)


def project_graph_nodes(cur, project_id: int) -> list[dict]:
    """A project's active deliverables, ordered by due date."""
    cur.execute(f"SELECT * FROM ({SELECT}) AS t WHERE project_id = %s AND NOT is_archived "  # nosec B608
                "ORDER BY due_date NULLS LAST, id", [project_id])
    return cur.fetchall()


def is_assigned_to_project(cur, project_id: int, user_id: int) -> bool:
    """True if the user has an active booking on the project."""
    cur.execute("SELECT 1 FROM project_assignments WHERE project_id = %s AND user_id = %s AND NOT is_archived",
                [project_id, user_id])
    return bool(cur.fetchone())


def active_ids_on_project(cur, project_id: int, ids: list[int]) -> set[int]:
    """Which of the given ids are active deliverables on the project."""
    cur.execute("SELECT id FROM deliverables WHERE id = ANY(%s::int[]) AND project_id = %s AND NOT is_archived",
                [ids, project_id])
    return {r["id"] for r in cur.fetchall()}


def find_dependency_loop(cur, deliverable_id: int, depends_on: list[int]) -> list[int] | None:
    """Path from a new dependency back to the deliverable (a loop), or None."""
    # A loop exists if this deliverable is reachable from any new dependency
    cur.execute(
        """
        WITH RECURSIVE reach(id, path) AS (
            SELECT d, ARRAY[d] FROM unnest(%s::int[]) AS d
            UNION ALL
            SELECT dd.depends_on_id, r.path || dd.depends_on_id
            FROM deliverable_dependencies dd JOIN reach r ON dd.deliverable_id = r.id
            WHERE dd.archived_at IS NULL AND NOT dd.depends_on_id = ANY(r.path)
        )
        SELECT path FROM reach WHERE id = %s LIMIT 1
        """,
        [depends_on, deliverable_id],
    )
    loop = cur.fetchone()
    return loop["path"] if loop else None


def titles_by_id(cur, ids: list[int]) -> dict[int, str]:
    """Titles of the given deliverables, keyed by id."""
    cur.execute("SELECT id, title FROM deliverables WHERE id = ANY(%s::int[])", [ids])
    return {r["id"]: r["title"] for r in cur.fetchall()}


def set_dependencies(cur, user_id: int, deliverable_id: int, depends_on: list[int]) -> None:
    """Replace a deliverable's active dependency links (removed links are archived)."""
    cur.execute(
        "UPDATE deliverable_dependencies SET archived_at = now() "
        "WHERE deliverable_id = %s AND archived_at IS NULL AND NOT depends_on_id = ANY(%s::int[])",
        [deliverable_id, depends_on],
    )
    for depends_on_id in depends_on:
        cur.execute(
            """INSERT INTO deliverable_dependencies (deliverable_id, depends_on_id, created_by)
               SELECT %s, %s, %s WHERE NOT EXISTS (
                   SELECT 1 FROM deliverable_dependencies
                   WHERE deliverable_id = %s AND depends_on_id = %s AND archived_at IS NULL)""",
            [deliverable_id, depends_on_id, user_id, deliverable_id, depends_on_id],
        )


def open_dependencies(cur, deliverable_id: int) -> list[dict]:
    """Active dependencies of a deliverable that are not done yet."""
    cur.execute(
        """SELECT x.id, x.title, x.status FROM deliverable_dependencies dd
           JOIN deliverables x ON x.id = dd.depends_on_id
           WHERE dd.deliverable_id = %s AND dd.archived_at IS NULL AND NOT x.is_archived AND x.status <> 'done'
           ORDER BY x.id""",
        [deliverable_id],
    )
    return cur.fetchall()


def insert_deliverable(cur, project_id: int, data: dict, is_milestone: bool, user_id: int) -> int:
    """Insert a deliverable and return the new id."""
    cur.execute(
        """
        INSERT INTO deliverables (project_id, title, description, status, start_date, due_date, assignee_id,
                                  progress_pct, is_milestone, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        [project_id, data["title"], data.get("description", ""), data.get("status", "todo"),
         data.get("start_date"), data.get("due_date"), data.get("assignee_id"), data.get("progress_pct", 0),
         is_milestone, user_id],
    )
    return cur.fetchone()["id"]


def update_deliverable(cur, deliverable_id: int, data: dict) -> None:
    """Update the given columns of a deliverable (column names come from a validated schema)."""
    assignments = ", ".join(f"{name} = %s" for name in data)
    cur.execute(f"UPDATE deliverables SET {assignments}, updated_at = now() WHERE id = %s",  # nosec B608
                [*data.values(), deliverable_id])


def archive_deliverable(cur, deliverable_id: int) -> None:
    """Mark a deliverable archived."""
    cur.execute("UPDATE deliverables SET is_archived = TRUE, archived_at = now(), updated_at = now() WHERE id = %s",
                [deliverable_id])


def restore_deliverable(cur, deliverable_id: int) -> None:
    """Restore an archived deliverable."""
    cur.execute("UPDATE deliverables SET is_archived = FALSE, archived_at = NULL, updated_at = now() WHERE id = %s",
                [deliverable_id])
