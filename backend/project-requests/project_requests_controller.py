"""
Project requests CONTROLLER: the routes for project requests.

Each route reads the request, checks permissions and rules, calls the model
(project_requests_model) for data and returns a view (project_requests_view).

Managers submit requests; only pending requests can be edited, withdrawn,
approved or rejected. Approving creates the project with the requester as
its manager.
"""

import project_requests_model as model
import project_requests_view as view
from shared import audit
from shared.errors import bad_request, conflict, forbidden, not_found
from shared.http import Request, Router
from shared.query import Filters, choice_param, int_param, order_by
from shared.rbac import ADMIN, MANAGER, require_role
from shared.schema import REQUEST_STATUSES
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


def _load(cur, user: dict, request_id: int, lock: bool = False) -> dict:
    """Fetch a request visible to the user (admin or requester) or raise 404."""
    row = model.get_request(cur, request_id, lock=lock)
    if row is None or (user["role"] != ADMIN and row["requested_by"] != user["id"]):
        raise not_found("Project request")
    return row


def _require_pending(row: dict) -> None:
    """Only pending requests can change."""
    if row["status"] != "pending":
        raise conflict(f"Request is already {row['status']}")


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
    return view.request_list(model.list_requests(cur, filters, order_by(q, model.SORTS, "-created_at"), q))


@router.post("/")
def create_request(request: Request, cur) -> dict:
    """Submit a project request (managers)."""
    user = request.user
    if user["role"] != MANAGER:
        raise forbidden("Only managers submit project requests; admins create projects directly")
    data = validate(request.body, REQUEST_SCHEMA)
    check_date_range(data["proposed_start_date"], data["proposed_end_date"],
                     "proposed_start_date", "proposed_end_date")
    request_id = model.insert_request(cur, user["id"], data)
    audit.record(cur, user, "project_request", request_id, "create", f"requested project {data['name']}", data)
    return view.request(model.get_request(cur, request_id), 201)


@router.get("/{id}")
def get_one(request: Request, cur) -> dict:
    """View a project request."""
    return view.request(_load(cur, request.user, request.params["id"]))


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
    model.update_request(cur, row["id"], data)
    audit.record(cur, user, "project_request", row["id"], "update",
                 f"updated project request {row['name']}", audit.diff(row, data))
    return view.request(model.get_request(cur, row["id"]))


@router.post("/{id}/withdraw")
def withdraw(request: Request, cur) -> dict:
    """Withdraw a pending request (requester only)."""
    user = request.user
    row = _load(cur, user, request.params["id"], lock=True)
    if row["requested_by"] != user["id"]:
        raise forbidden("Only the requester can withdraw a request")
    _require_pending(row)
    model.withdraw_request(cur, row["id"])
    audit.record(cur, user, "project_request", row["id"], "archive", f"withdrew project request {row['name']}")
    return view.request(model.get_request(cur, row["id"]))


@router.post("/{id}/approve")
def approve(request: Request, cur) -> dict:
    """Approve a request, creating the project with the requester as its manager (admin)."""
    user = request.user
    require_role(user, ADMIN)
    row = _load(cur, user, request.params["id"], lock=True)
    _require_pending(row)
    note = validate(request.body, REVIEW_SCHEMA)["review_note"] or ""
    requester = model.get_user(cur, row["requested_by"])
    if not requester["is_active"] or requester["role"] not in (ADMIN, MANAGER):
        raise conflict("The requester is no longer an active manager; reject the request instead")
    project_id = model.insert_project(cur, user["id"], {
        "name": row["name"],
        "description": row["description"],
        "start_date": row["proposed_start_date"],
        "end_date": row["proposed_end_date"],
        "budget_cents": row["proposed_budget_cents"],
        "manager_id": row["requested_by"],
    })
    model.approve_request(cur, row["id"], user["id"], note, project_id)
    project = model.get_project(cur, project_id)
    audit.record(cur, user, "project_request", row["id"], "update",
                 f"approved project request {row['name']}, creating {project['code']}", {"project_id": project_id})
    return view.approved(model.get_request(cur, row["id"]), project)


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
    model.reject_request(cur, row["id"], user["id"], note)
    audit.record(cur, user, "project_request", row["id"], "update", f"rejected project request {row['name']}",
                 {"review_note": note})
    return view.request(model.get_request(cur, row["id"]))
