"""
Assignments service: assign people to projects with weekly hours.

Routes (relative to /api/assignments):
    GET    /        list assignments (admin: all, manager: their projects and
                    direct reports, employee: their own)
    POST   /        assign a person to a project
    GET    /{id}    view assignment
    PUT    /{id}    change hours or project role
    DELETE /{id}    remove a person from a project

Rules:
- admins can assign any active employee or manager to any active project;
- managers can assign their direct reports to projects they manage;
- a person's weekly hours across non-archived projects cannot exceed 40.
"""

from shared import audit
from shared.app import make_handler
from shared.errors import bad_request, conflict, forbidden, not_found
from shared.http import Request, Router, response
from shared.query import Filters, choice_param, int_param, order_by, paginated
from shared.rbac import ADMIN, EMPLOYEE, MANAGER, load_managed_project
from shared.rules import MAX_WEEKLY_HOURS, check_capacity
from shared.users import get_user
from shared.validation import Field, validate

router = Router()

CREATE_SCHEMA = {
    "project_id": Field(kind="int", required=True, min_value=1),
    "user_id": Field(kind="int", required=True, min_value=1),
    "hours_per_week": Field(kind="int", required=True, min_value=1, max_value=MAX_WEEKLY_HOURS),
    "project_role": Field(max_length=100),
}
UPDATE_SCHEMA = {
    "hours_per_week": Field(kind="int", required=True, min_value=1, max_value=MAX_WEEKLY_HOURS),
    "project_role": Field(max_length=100),
}

SELECT = """
    SELECT a.id, a.project_id, a.user_id, a.project_role, a.hours_per_week, a.assigned_by,
           a.created_at, a.updated_at,
           p.code AS project_code, p.name AS project_name, p.is_archived AS project_is_archived,
           p.manager_id AS project_manager_id,
           u.employee_id, u.first_name || ' ' || u.last_name AS full_name, u.job_title,
           u.manager_id AS user_manager_id
    FROM project_assignments a
    JOIN projects p ON p.id = a.project_id
    JOIN users u ON u.id = a.user_id
"""
SORTS = {"full_name": "full_name", "project_name": "project_name", "hours_per_week": "hours_per_week",
         "created_at": "created_at"}


def _scope(user: dict, filters: Filters) -> Filters:
    """Restrict assignments to those the user may see."""
    if user["role"] == MANAGER:
        filters.add("(project_manager_id = %s OR user_manager_id = %s)", user["id"], user["id"])
    elif user["role"] == EMPLOYEE:
        filters.eq("user_id", user["id"])
    return filters


def _load(cur, user: dict, assignment_id: int) -> dict:
    """Fetch an assignment visible to the user or raise 404."""
    filters = _scope(user, Filters()).eq("id", assignment_id)
    cur.execute(f"SELECT * FROM ({SELECT}) AS t {filters.where()}", filters.params)  # nosec B608
    row = cur.fetchone()
    if row is None:
        raise not_found("Assignment")
    return row


@router.get("/")
def list_assignments(request: Request, cur) -> dict:
    """List assignments with filters."""
    user, q = request.user, request.query
    filters = _scope(user, Filters())
    filters.eq("project_id", int_param(q, "project_id"))
    filters.eq("user_id", int_param(q, "user_id"))
    archived = choice_param(q, "archived", ("true", "false", "all")) or "false"
    if archived != "all":
        filters.eq("project_is_archived", archived == "true")
    filters.search(["full_name", "employee_id", "project_name", "project_code", "project_role"], q.get("q"))
    return response(200, paginated(cur, SELECT, filters, order_by(q, SORTS, "full_name"), q))


@router.post("/")
def create_assignment(request: Request, cur) -> dict:
    """Assign a person to a project."""
    user = request.user
    data = validate(request.body, CREATE_SCHEMA)
    project = load_managed_project(cur, user, data["project_id"])
    assignee = get_user(cur, data["user_id"])
    if assignee is None:
        raise bad_request("Validation failed", {"user_id": "user does not exist"})
    if not assignee["is_active"] or assignee["role"] not in (EMPLOYEE, MANAGER):
        raise bad_request("Validation failed", {"user_id": "must be an active employee or manager"})
    if user["role"] != ADMIN and assignee["manager_id"] != user["id"]:
        raise forbidden("Managers can only assign their direct reports")
    cur.execute("SELECT 1 FROM project_assignments WHERE project_id = %s AND user_id = %s",
                [project["id"], assignee["id"]])
    if cur.fetchone():
        raise conflict("This person is already assigned to the project; update their hours instead")
    check_capacity(cur, assignee["id"], data["hours_per_week"])
    cur.execute(
        """
        INSERT INTO project_assignments (project_id, user_id, project_role, hours_per_week, assigned_by)
        VALUES (%s, %s, %s, %s, %s) RETURNING id
        """,
        [project["id"], assignee["id"], data["project_role"] or "", data["hours_per_week"], user["id"]],
    )
    assignment_id = cur.fetchone()["id"]
    audit.record(cur, user["id"], "assignment", assignment_id, "create", data)
    return response(201, _load(cur, user, assignment_id))


@router.get("/{id}")
def get_one(request: Request, cur) -> dict:
    """View an assignment."""
    return response(200, _load(cur, request.user, request.params["id"]))


@router.put("/{id}")
def update_assignment(request: Request, cur) -> dict:
    """Change weekly hours or project role."""
    user = request.user
    row = _load(cur, user, request.params["id"])
    load_managed_project(cur, user, row["project_id"])
    data = validate(request.body, UPDATE_SCHEMA, partial=True)
    if not data:
        raise bad_request("Nothing to update")
    if "hours_per_week" in data:
        if data["hours_per_week"] is None:
            raise bad_request("Validation failed", {"hours_per_week": "is required"})
        check_capacity(cur, row["user_id"], data["hours_per_week"], exclude_assignment_id=row["id"])
    if "project_role" in data and data["project_role"] is None:
        data["project_role"] = ""
    assignments = ", ".join(f"{name} = %s" for name in data)
    cur.execute(f"UPDATE project_assignments SET {assignments}, updated_at = now() WHERE id = %s",  # nosec B608
                [*data.values(), row["id"]])
    audit.record(cur, user["id"], "assignment", row["id"], "update", audit.diff(row, data))
    return response(200, _load(cur, user, row["id"]))


@router.delete("/{id}")
def delete_assignment(request: Request, cur) -> dict:
    """Remove a person from a project; their open deliverables there become unassigned."""
    user = request.user
    row = _load(cur, user, request.params["id"])
    load_managed_project(cur, user, row["project_id"])
    cur.execute(
        "UPDATE deliverables SET assignee_id = NULL, updated_at = now() "
        "WHERE project_id = %s AND assignee_id = %s AND status <> 'done'",
        [row["project_id"], row["user_id"]],
    )
    cur.execute("DELETE FROM project_assignments WHERE id = %s", [row["id"]])
    audit.record(cur, user["id"], "assignment", row["id"], "delete",
                 {"project_id": row["project_id"], "user_id": row["user_id"],
                  "hours_per_week": row["hours_per_week"]})
    return response(204)


handler = make_handler(router, "assignments")
