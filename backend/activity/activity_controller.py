"""
Activity CONTROLLER: the routes for notifications and the audit log.

Each route reads the request, checks permissions and rules, calls the model
(activity_model) for data and returns a view (activity_view).
"""

import activity_model as model
import activity_view as view
from shared.errors import not_found
from shared.http import Request, Router
from shared.query import Filters, choice_param, date_param, int_param, order_by
from shared.rbac import ADMIN, require_role

router = Router()

ENTITIES = ("user", "project", "project_request", "assignment", "deliverable", "time_entry")
ACTIONS = ("create", "update", "archive")


@router.get("/notifications")
def list_notifications(request: Request, cur) -> dict:
    """The caller's notifications, newest first."""
    user, q = request.user, request.query
    filters = Filters().eq("user_id", user["id"])
    if choice_param(q, "unread", ("true", "false")) == "true":
        filters.add("read_at IS NULL")
    result = model.list_notifications(cur, filters, q)
    return view.notification_list(result, model.count_unread(cur, user["id"]))


@router.post("/notifications/read-all")
def read_all(request: Request, cur) -> dict:
    """Mark all of the caller's notifications as read."""
    return view.all_read(model.mark_all_read(cur, request.user["id"]))


@router.post("/notifications/{id}/read")
def read_one(request: Request, cur) -> dict:
    """Mark one notification as read."""
    row = model.mark_read(cur, request.params["id"], request.user["id"])
    if row is None:
        raise not_found("Notification")
    return view.notification(row)


@router.get("/audit")
def audit_log(request: Request, cur) -> dict:
    """Every create, edit and archive, with who did it (admin only)."""
    require_role(request.user, ADMIN)
    q = request.query
    filters = Filters()
    filters.eq("entity", choice_param(q, "entity", ENTITIES))
    filters.eq("action", choice_param(q, "action", ACTIONS))
    filters.eq("actor_id", int_param(q, "actor_id"))
    filters.eq("entity_id", int_param(q, "entity_id"))
    filters.search(["summary", "actor_name"], q.get("q"))
    date_from = date_param(q, "from")
    if date_from:
        filters.add("created_at >= %s", date_from)
    date_to = date_param(q, "to")
    if date_to:
        filters.add("created_at < %s::date + 1", date_to)
    return view.audit_list(model.list_audit(cur, filters, order_by(q, model.SORTS, "-created_at"), q))
