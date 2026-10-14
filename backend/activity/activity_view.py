"""
Activity VIEW: the JSON shapes the activity service sends back.
"""

from shared.http import response


def notification_list(result: dict, unread: int) -> dict:
    """A page of notifications plus the total unread count."""
    result["unread"] = unread
    return response(200, result)


def all_read(updated: int) -> dict:
    """How many notifications were just marked as read."""
    return response(200, {"updated": updated, "unread": 0})


def notification(row: dict) -> dict:
    """Response with one notification."""
    return response(200, row)


def audit_list(result: dict) -> dict:
    """A page of the audit log."""
    return response(200, result)
