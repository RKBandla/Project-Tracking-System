"""
Activity MODEL: every database query for notifications and the audit log.

The controller calls these functions; nothing here knows about HTTP.
"""

from shared.query import Filters, order_by, paginated

NOTIFICATION_SELECT = "SELECT * FROM notifications"
AUDIT_SELECT = """
    SELECT a.*, CASE WHEN u.id IS NULL THEN 'System' ELSE u.first_name || ' ' || u.last_name END AS actor_name,
           u.role AS actor_role
    FROM audit_log a LEFT JOIN users u ON u.id = a.actor_id
"""
SORTS = {"created_at": "created_at"}


def list_notifications(cur, filters: Filters, query: dict) -> dict:
    """One page of notifications, newest first."""
    return paginated(cur, NOTIFICATION_SELECT, filters,
                     order_by({"sort": "-created_at"}, SORTS, "-created_at"), query)


def count_unread(cur, user_id: int) -> int:
    """How many of a user's notifications are unread."""
    cur.execute("SELECT count(*) AS n FROM notifications WHERE user_id = %s AND read_at IS NULL", [user_id])
    return cur.fetchone()["n"]


def mark_all_read(cur, user_id: int) -> int:
    """Mark all of a user's unread notifications as read; return how many changed."""
    cur.execute("UPDATE notifications SET read_at = now() WHERE user_id = %s AND read_at IS NULL",
                [user_id])
    return cur.rowcount


def mark_read(cur, notification_id: int, user_id: int) -> dict | None:
    """Mark one of a user's notifications as read and return it (None if not theirs)."""
    cur.execute(
        "UPDATE notifications SET read_at = COALESCE(read_at, now()) WHERE id = %s AND user_id = %s RETURNING *",
        [notification_id, user_id],
    )
    return cur.fetchone()


def list_audit(cur, filters: Filters, order_sql: str, query: dict) -> dict:
    """One page of the audit log, with the actor's name and role."""
    return paginated(cur, AUDIT_SELECT, filters, order_sql, query)
