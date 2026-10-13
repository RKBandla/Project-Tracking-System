"""
Role-based access control shared by every service.

Visibility rules for projects (and everything that hangs off a project):
- admin:    every project
- manager:  projects they manage
- employee: projects they are currently assigned to

Projects that are not visible to a caller are reported as 404 so their
existence is not leaked.
"""

from .errors import conflict, forbidden, not_found

ADMIN = "admin"
MANAGER = "manager"
EMPLOYEE = "employee"

PROJECT_SELECT = """
    SELECT p.*,
           CASE WHEN m.id IS NULL THEN NULL ELSE m.first_name || ' ' || m.last_name END AS manager_name
    FROM projects p
    LEFT JOIN users m ON m.id = p.manager_id
"""


def require_role(user: dict, *roles: str) -> None:
    """Raise 403 unless the user has one of the given roles."""
    if user["role"] not in roles:
        raise forbidden()


def is_admin(user: dict) -> bool:
    """True for admins."""
    return user["role"] == ADMIN


def visible_project_ids(user: dict) -> tuple[str, list] | None:
    """
    Return a subquery selecting the ids of projects the user may view,
    or None when the user may view every project.
    """
    if user["role"] == ADMIN:
        return None
    if user["role"] == MANAGER:
        return "SELECT id FROM projects WHERE manager_id = %s", [user["id"]]
    return "SELECT project_id FROM project_assignments WHERE user_id = %s", [user["id"]]


def can_view_project(cur, user: dict, project: dict) -> bool:
    """Check whether a user may view a specific project."""
    if user["role"] == ADMIN:
        return True
    if user["role"] == MANAGER:
        return project["manager_id"] == user["id"]
    cur.execute(
        "SELECT 1 FROM project_assignments WHERE project_id = %s AND user_id = %s",
        [project["id"], user["id"]],
    )
    return cur.fetchone() is not None


def can_manage_project(user: dict, project: dict) -> bool:
    """Admins manage every project; managers manage the projects assigned to them."""
    return user["role"] == ADMIN or (user["role"] == MANAGER and project["manager_id"] == user["id"])


def get_project(cur, project_id: int, lock: bool = False) -> dict | None:
    """Fetch a project with its manager name, optionally locking the row."""
    if lock:
        cur.execute("SELECT id FROM projects WHERE id = %s FOR UPDATE", [project_id])
    cur.execute(PROJECT_SELECT + " WHERE p.id = %s", [project_id])
    return cur.fetchone()


def load_visible_project(cur, user: dict, project_id: int) -> dict:
    """Return a project the user may view, else raise 404."""
    project = get_project(cur, project_id)
    if project is None or not can_view_project(cur, user, project):
        raise not_found("Project")
    return project


def load_managed_project(cur, user: dict, project_id: int, for_write: bool = True) -> dict:
    """
    Return a project the user may manage.

    Raises 404 if it is not visible, 403 if visible but not manageable and
    409 if ``for_write`` and the project is archived (archived projects are read-only).
    """
    project = load_visible_project(cur, user, project_id)
    if not can_manage_project(user, project):
        raise forbidden("Only an admin or the project's manager can change this project")
    if for_write and project["is_archived"]:
        raise conflict("Project is archived and read-only; reactivate it first")
    return project
