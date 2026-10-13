"""
Audit trail: every change is recorded so history is kept even though
projects are archived rather than deleted.
"""

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def _default(value: Any) -> Any:
    """Serialise Decimal and date values for JSONB."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def record(cur, actor_id: int | None, entity: str, entity_id: int, action: str,
           changes: dict | None = None) -> None:
    """Insert an audit log entry."""
    cur.execute(
        "INSERT INTO audit_log (actor_id, entity, entity_id, action, changes) VALUES (%s, %s, %s, %s, %s)",
        [actor_id, entity, entity_id, action,
         json.dumps(changes, default=_default) if changes is not None else None],
    )


def diff(before: dict, after: dict) -> dict:
    """Return ``{field: {"from": old, "to": new}}`` for fields whose value changed."""
    return {
        key: {"from": before.get(key), "to": value}
        for key, value in after.items()
        if before.get(key) != value
    }
