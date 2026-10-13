"""
Project requests service: managers ask admins to create projects.

Routes (relative to /api/project-requests):
    GET  /                 list requests (admin: all, manager: own)
    POST /                 submit a request (manager)
    GET  /{id}             view request (admin or requester)
    PUT  /{id}             edit a pending request (requester)
    POST /{id}/withdraw    withdraw a pending request (requester)
    POST /{id}/approve     approve and create the project with the requester as manager (admin)
    POST /{id}/reject      reject with a note (admin)
"""

from shared import audit
from shared.app import make_handler
from shared.errors import bad_request, conflict, forbidden, not_found
from shared.http import Request, Router, response
from shared.projects import get_project, insert_project, present_project
from shared.query import Filters, choice_param, int_param, order_by, paginated
from shared.rbac import ADMIN, MANAGER, require_role
from shared.schema import REQUEST_STATUSES
from shared.users import get_user
from shared.validation import Field, check_date_range, validate

router = Router()

REQUEST_SCHEMA = {
    "name": Field(required=True, max_length=200),
    "description": Field(kind="text", max_length=5000),
    "justification": Field(kind="text", max_length=5000),
    "proposed_start_date": Field(kind="date", nullable=True),
    "proposed_end_date": Field(kind="date", nullable=True),
    "proposed_budget_cents": Field(kind="int", min_value=0, max_value=10**14),
}
REVIEW_SCHEMA = {"review_note": Field(kind="text", max_length=2000)}

SELECT = """
    SELECT r.*,
           u.first_name || ' ' || u.last_name AS requested_by_name,
           CASE WHEN v.id IS NULL THEN NULL ELSE v.first_name || ' ' || v.last_name END AS reviewed_by_name,
           p.code AS project_code
    FROM project_requests r
    JOIN users u ON u.id = r.requested_by
    LEFT JOIN users v ON v.id = r.reviewed_by
    LEFT JOIN projects p ON p.id = r.project_id
"""
SORTS = {"created_at": "created_at", "name": "name", "status": "status",
         "proposed_budget_cents": "proposed_budget_cents", "proposed_start_date": "proposed_start_date"}


def _load(cur, user: dict, request_id: int, lock: bool = False) -> dict:
    """Fetch a request visible to the user (admin or requester) or raise 404."""
    if lock:
        cur.execute("SELECT id FROM project_requests WHERE id = %s FOR UPDATE", [request_id])
    cur.execute(SELECT + " WHERE r.id = %s", [request_id])
    row = cur.fetchone()
    if row is None or (user["role"] != ADMIN and row["requested_by"] != user["id"]):
        raise not_found("Project request")
    return row


def _require_pending(row: dict) -> None:
    """Only pending requests can change."""
    if row["status"] != "pending":
        raise conflict(f"Request is already {row['status']}")


def _reload(cur, request_id: int) -> dict:
    """Fetch a request after a change."""
    cur.execute(SELECT + " WHERE r.id = %s", [request_id])
    return cur.fetchone()


@router.get("/")
def list_requests(request: Request, cur) -> dict:
    """List project requests."""
    user, q = request.user, request.query
    require_role(user, ADMIN, MANAGER)
    filters = Filters()
    if user["role"] == MANAGER:
        filters.eq("requested_by", user["id"])
    else:
        filters.eq("requested_by", int_param(q, "requested_by"))
    filters.eq("status", choice_param(q, "status", REQUEST_STATUSES))
    filters.search(["name", "description", "requested_by_name"], q.get("q"))
    return response(200, paginated(cur, SELECT, filters, order_by(q, SORTS, "-created_at"), q))


@router.post("/")
def create_request(request: Request, cur) -> dict:
    """Submit a project request (managers)."""
    user = request.user
    if user["role"] != MANAGER:
        raise forbidden("Only managers submit project requests; admins create projects directly")
    data = validate(request.body, REQUEST_SCHEMA)
    check_date_range(data["proposed_start_date"], data["proposed_end_date"],
                     "proposed_start_date", "proposed_end_date")
    cur.execute(
        """
        INSERT INTO project_requests (requested_by, name, description, justification,
                                      proposed_start_date, proposed_end_date, proposed_budget_cents)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        [user["id"], data["name"], data["description"] or "", data["justification"] or "",
         data["proposed_start_date"], data["proposed_end_date"], data["proposed_budget_cents"] or 0],
    )
    request_id = cur.fetchone()["id"]
    audit.record(cur, user, "project_request", request_id, "create", f"requested project {data['name']}", data)
    return response(201, _reload(cur, request_id))


@router.get("/{id}")
def get_one(request: Request, cur) -> dict:
    """View a project request."""
    return response(200, _load(cur, request.user, request.params["id"]))


@router.put("/{id}")
def update_request(request: Request, cur) -> dict:
    """Edit a pending request (requester only)."""
    user = request.user
    row = _load(cur, user, request.params["id"], lock=True)
    if row["requested_by"] != user["id"]:
        raise forbidden("Only the requester can edit a request")
    _require_pending(row)
    data = validate(request.body, REQUEST_SCHEMA, partial=True)
    if not data:
        raise bad_request("Nothing to update")
    if "name" in data and data["name"] is None:
        raise bad_request("Validation failed", {"name": "is required"})
    for text in ("description", "justification"):
        if text in data and data[text] is None:
            data[text] = ""
    if "proposed_budget_cents" in data and data["proposed_budget_cents"] is None:
        data["proposed_budget_cents"] = 0
    check_date_range(data.get("proposed_start_date", row["proposed_start_date"]),
                     data.get("proposed_end_date", row["proposed_end_date"]),
                     "proposed_start_date", "proposed_end_date")
    assignments = ", ".join(f"{name} = %s" for name in data)
    cur.execute(f"UPDATE project_requests SET {assignments}, updated_at = now() WHERE id = %s",  # nosec B608
                [*data.values(), row["id"]])
    audit.record(cur, user, "project_request", row["id"], "update",
                 f"updated project request {row['name']}", audit.diff(row, data))
    return response(200, _reload(cur, row["id"]))


@router.post("/{id}/withdraw")
def withdraw(request: Request, cur) -> dict:
    """Withdraw a pending request (requester only)."""
    user = request.user
    row = _load(cur, user, request.params["id"], lock=True)
    if row["requested_by"] != user["id"]:
        raise forbidden("Only the requester can withdraw a request")
    _require_pending(row)
    cur.execute("UPDATE project_requests SET status = 'withdrawn', updated_at = now() WHERE id = %s", [row["id"]])
    audit.record(cur, user, "project_request", row["id"], "archive", f"withdrew project request {row['name']}")
    return response(200, _reload(cur, row["id"]))


@router.post("/{id}/approve")
def approve(request: Request, cur) -> dict:
    """Approve a request, creating the project with the requester as its manager (admin)."""
    user = request.user
    require_role(user, ADMIN)
    row = _load(cur, user, request.params["id"], lock=True)
    _require_pending(row)
    note = validate(request.body, REVIEW_SCHEMA)["review_note"] or ""
    requester = get_user(cur, row["requested_by"])
    if not requester["is_active"] or requester["role"] not in (ADMIN, MANAGER):
        raise conflict("The requester is no longer an active manager; reject the request instead")
    project_id = insert_project(cur, user["id"], {
        "name": row["name"],
        "description": row["description"],
        "start_date": row["proposed_start_date"],
        "end_date": row["proposed_end_date"],
        "budget_cents": row["proposed_budget_cents"],
        "manager_id": row["requested_by"],
    })
    cur.execute(
        """UPDATE project_requests SET status = 'approved', reviewed_by = %s, reviewed_at = now(),
                  review_note = %s, project_id = %s, updated_at = now() WHERE id = %s""",
        [user["id"], note, project_id, row["id"]],
    )
    project = get_project(cur, project_id)
    audit.record(cur, user, "project_request", row["id"], "update",
                 f"approved project request {row['name']}, creating {project['code']}", {"project_id": project_id})
    return response(200, {"request": _reload(cur, row["id"]), "project": present_project(project)})


@router.post("/{id}/reject")
def reject(request: Request, cur) -> dict:
    """Reject a request with a note explaining why (admin)."""
    user = request.user
    require_role(user, ADMIN)
    row = _load(cur, user, request.params["id"], lock=True)
    _require_pending(row)
    note = validate(request.body, REVIEW_SCHEMA)["review_note"]
    if not note:
        raise bad_request("Validation failed", {"review_note": "is required when rejecting"})
    cur.execute(
        """UPDATE project_requests SET status = 'rejected', reviewed_by = %s, reviewed_at = now(),
                  review_note = %s, updated_at = now() WHERE id = %s""",
        [user["id"], note, row["id"]],
    )
    audit.record(cur, user, "project_request", row["id"], "update", f"rejected project request {row['name']}",
                 {"review_note": note})
    return response(200, _reload(cur, row["id"]))


handler = make_handler(router, "project-requests")
