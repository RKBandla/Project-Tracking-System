"""
Deliverables service: work items tracked against a project.

Routes (relative to /api/deliverables):
    GET    /        list deliverables on visible projects (search, filters, sort)
    POST   /        create deliverable (admin, or the project's manager)
    GET    /{id}    view deliverable
    PUT    /{id}    update deliverable (admin, or the project's manager)
    DELETE /{id}    delete deliverable (admin, or the project's manager)

Employees can view deliverables on the projects they are assigned to.
Deliverables on archived projects are read-only.
"""

from shared import audit
from shared.app import make_handler
from shared.errors import bad_request, not_found
from shared.http import Request, Router, response
from shared.query import Filters, choice_param, date_param, int_param, order_by, paginated
from shared.rbac import load_managed_project, visible_project_ids
from shared.schema import DELIVERABLE_STATUSES
from shared.validation import Field, validate

router = Router()

FIELDS = {
    "title": Field(required=True, max_length=200),
    "description": Field(kind="text", max_length=5000),
    "status": Field(choices=DELIVERABLE_STATUSES),
    "due_date": Field(kind="date", nullable=True),
    "assignee_id": Field(kind="int", nullable=True, min_value=1),
    "progress_pct": Field(kind="int", min_value=0, max_value=100),
}
CREATE_SCHEMA = {"project_id": Field(kind="int", required=True, min_value=1), **FIELDS}

SELECT = """
    SELECT d.*, p.code AS project_code, p.name AS project_name, p.is_archived AS project_is_archived,
           CASE WHEN u.id IS NULL THEN NULL ELSE u.first_name || ' ' || u.last_name END AS assignee_name,
           (d.status <> 'done' AND d.due_date < CURRENT_DATE) AS is_overdue
    FROM deliverables d
    JOIN projects p ON p.id = d.project_id
    LEFT JOIN users u ON u.id = d.assignee_id
"""
SORTS = {"due_date": "due_date", "title": "title", "status": "status", "progress_pct": "progress_pct",
         "created_at": "created_at", "updated_at": "updated_at", "project_name": "project_name"}


def _scope(user: dict, filters: Filters) -> Filters:
    """Restrict to deliverables on projects the user may view."""
    visible = visible_project_ids(user)
    if visible is not None:
        sql, params = visible
        filters.add(f"project_id IN ({sql})", *params)
    return filters


def _load(cur, user: dict, deliverable_id: int) -> dict:
    """Fetch a visible deliverable or raise 404."""
    filters = _scope(user, Filters()).eq("id", deliverable_id)
    cur.execute(f"SELECT * FROM ({SELECT}) AS t {filters.where()}", filters.params)  # nosec B608
    row = cur.fetchone()
    if row is None:
        raise not_found("Deliverable")
    return row


def _check_assignee(cur, project: dict, assignee_id: int | None) -> None:
    """An assignee must be on the project team or be its manager."""
    if assignee_id is None or assignee_id == project["manager_id"]:
        return
    cur.execute("SELECT 1 FROM project_assignments WHERE project_id = %s AND user_id = %s",
                [project["id"], assignee_id])
    if not cur.fetchone():
        raise bad_request("Validation failed", {"assignee_id": "must be assigned to the project"})


def _normalise(data: dict) -> dict:
    """Apply defaults: done means 100% progress; empty text becomes ''."""
    if data.get("status") == "done" and "progress_pct" not in data:
        data["progress_pct"] = 100
    if "description" in data and data["description"] is None:
        data["description"] = ""
    for required in ("status", "progress_pct"):
        if required in data and data[required] is None:
            raise bad_request("Validation failed", {required: "is required"})
    return data


@router.get("/")
def list_deliverables(request: Request, cur) -> dict:
    """List deliverables."""
    user, q = request.user, request.query
    filters = _scope(user, Filters())
    filters.eq("project_id", int_param(q, "project_id"))
    filters.eq("assignee_id", int_param(q, "assignee_id"))
    filters.eq("status", choice_param(q, "status", DELIVERABLE_STATUSES))
    filters.search(["title", "description", "project_name", "assignee_name"], q.get("q"))
    if choice_param(q, "overdue", ("true", "false")) == "true":
        filters.add("is_overdue")
    due_after = date_param(q, "due_after")
    if due_after:
        filters.add("due_date >= %s", due_after)
    due_before = date_param(q, "due_before")
    if due_before:
        filters.add("due_date <= %s", due_before)
    archived = choice_param(q, "archived", ("true", "false", "all")) or "all"
    if archived != "all":
        filters.eq("project_is_archived", archived == "true")
    return response(200, paginated(cur, SELECT, filters, order_by(q, SORTS, "due_date"), q))


@router.post("/")
def create_deliverable(request: Request, cur) -> dict:
    """Create a deliverable on a managed project."""
    user = request.user
    data = validate(request.body, CREATE_SCHEMA)
    project = load_managed_project(cur, user, data["project_id"])
    data = _normalise({k: v for k, v in data.items() if v is not None or k in ("due_date", "assignee_id")})
    _check_assignee(cur, project, data.get("assignee_id"))
    cur.execute(
        """
        INSERT INTO deliverables (project_id, title, description, status, due_date, assignee_id,
                                  progress_pct, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        [project["id"], data["title"], data.get("description", ""), data.get("status", "todo"),
         data.get("due_date"), data.get("assignee_id"), data.get("progress_pct", 0), user["id"]],
    )
    deliverable_id = cur.fetchone()["id"]
    audit.record(cur, user["id"], "deliverable", deliverable_id, "create", data)
    return response(201, _load(cur, user, deliverable_id))


@router.get("/{id}")
def get_one(request: Request, cur) -> dict:
    """View a deliverable."""
    return response(200, _load(cur, request.user, request.params["id"]))


@router.put("/{id}")
def update_deliverable(request: Request, cur) -> dict:
    """Update a deliverable on a managed project."""
    user = request.user
    row = _load(cur, user, request.params["id"])
    project = load_managed_project(cur, user, row["project_id"])
    data = validate(request.body, FIELDS, partial=True)
    if not data:
        raise bad_request("Nothing to update")
    if "title" in data and data["title"] is None:
        raise bad_request("Validation failed", {"title": "is required"})
    data = _normalise(data)
    if "assignee_id" in data and data["assignee_id"] != row["assignee_id"]:
        _check_assignee(cur, project, data["assignee_id"])
    changes = audit.diff(row, data)
    if changes:
        assignments = ", ".join(f"{name} = %s" for name in data)
        cur.execute(f"UPDATE deliverables SET {assignments}, updated_at = now() WHERE id = %s",  # nosec B608
                    [*data.values(), row["id"]])
        audit.record(cur, user["id"], "deliverable", row["id"], "update", changes)
    return response(200, _load(cur, user, row["id"]))


@router.delete("/{id}")
def delete_deliverable(request: Request, cur) -> dict:
    """Delete a deliverable on a managed project."""
    user = request.user
    row = _load(cur, user, request.params["id"])
    load_managed_project(cur, user, row["project_id"])
    cur.execute("DELETE FROM deliverables WHERE id = %s", [row["id"]])
    audit.record(cur, user["id"], "deliverable", row["id"], "delete",
                 {"project_id": row["project_id"], "title": row["title"]})
    return response(204)


handler = make_handler(router, "deliverables")
