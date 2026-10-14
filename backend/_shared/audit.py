"""
Audit trail and notifications.

Every create, edit or archive writes exactly one audit-log row, and everyone
above the actor in the reporting line gets an in-app notification.
"""

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .users import manager_chain


def _default(value: Any) -> Any:
    """Serialise Decimal and date values for JSONB."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def record(cur, actor: dict | None, entity: str, entity_id: int, action: str,
           summary: str, changes: dict | None = None) -> int:
    """
    Insert one audit row and notify the actor's managers.

    Args:
        actor: The user performing the change (None for system actions).
        entity: Entity type, e.g. ``project``.
        entity_id: Id of the changed row.
        action: ``create``, ``update``, ``archive``, ...
        summary: Short human description, e.g. ``created project PRJ-0001 Apollo``.
        changes: Optional field-level details.

    Returns:
        int: The audit row id.
    """
    cur.execute(
        "INSERT INTO audit_log (actor_id, entity, entity_id, action, summary, changes) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        [actor["id"] if actor else None, entity, entity_id, action, summary,
         json.dumps(changes, default=_default) if changes is not None else None],
    )
    audit_id = cur.fetchone()["id"]
    if actor:
        message = f"{actor['first_name']} {actor['last_name']} {summary}"
        for manager_id in manager_chain(cur, actor["id"]):
            cur.execute(
                "INSERT INTO notifications (user_id, audit_id, message, entity, entity_id) "
                "VALUES (%s, %s, %s, %s, %s)",
                [manager_id, audit_id, message, entity, entity_id],
            )
    return audit_id


def diff(before: dict, after: dict) -> dict:
    """Return ``{field: {"from": old, "to": new}}`` for fields whose value changed."""
    return {
        key: {"from": before.get(key), "to": value}
        for key, value in after.items()
        if before.get(key) != value
    }
