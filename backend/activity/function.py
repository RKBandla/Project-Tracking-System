"""
Activity service: in-app notifications and the audit log.

Routes (relative to /api/activity):
    GET  /notifications             the caller's notifications (?unread=true)
    POST /notifications/read-all    mark all as read
    POST /notifications/{id}/read   mark one as read
    GET  /audit                     audit log with search and filters (admin)
"""

from shared.app import make_handler
from shared.errors import not_found
from shared.http import Request, Router, response
from shared.query import Filters, choice_param, date_param, int_param, order_by, paginated
from shared.rbac import ADMIN, require_role

router = Router()

NOTIFICATION_SELECT = "SELECT * FROM notifications"
AUDIT_SELECT = """
    SELECT a.*, CASE WHEN u.id IS NULL THEN 'System' ELSE u.first_name || ' ' || u.last_name END AS actor_name,
           u.role AS actor_role
    FROM audit_log a LEFT JOIN users u ON u.id = a.actor_id
"""
ENTITIES = ("user", "project", "project_request", "assignment", "deliverable", "time_entry")
ACTIONS = ("create", "update", "archive")


@router.get("/notifications")
def list_notifications(request: Request, cur) -> dict:
    """The caller's notifications, newest first."""
    user, q = request.user, request.query
    filters = Filters().eq("user_id", user["id"])
    if choice_param(q, "unread", ("true", "false")) == "true":
        filters.add("read_at IS NULL")
    result = paginated(cur, NOTIFICATION_SELECT, filters,
                       order_by({"sort": "-created_at"}, {"created_at": "created_at"}, "-created_at"), q)
    cur.execute("SELECT count(*) AS n FROM notifications WHERE user_id = %s AND read_at IS NULL", [user["id"]])
    result["unread"] = cur.fetchone()["n"]
    return response(200, result)


@router.post("/notifications/read-all")
def read_all(request: Request, cur) -> dict:
    """Mark all of the caller's notifications as read."""
    cur.execute("UPDATE notifications SET read_at = now() WHERE user_id = %s AND read_at IS NULL",
                [request.user["id"]])
    return response(200, {"updated": cur.rowcount, "unread": 0})


@router.post("/notifications/{id}/read")
def read_one(request: Request, cur) -> dict:
    """Mark one notification as read."""
    cur.execute(
        "UPDATE notifications SET read_at = COALESCE(read_at, now()) WHERE id = %s AND user_id = %s RETURNING *",
        [request.params["id"], request.user["id"]],
    )
    row = cur.fetchone()
    if row is None:
        raise not_found("Notification")
    return response(200, row)


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
    return response(200, paginated(cur, AUDIT_SELECT, filters,
                                   order_by(q, {"created_at": "created_at"}, "-created_at"), q))


handler = make_handler(router, "activity")
