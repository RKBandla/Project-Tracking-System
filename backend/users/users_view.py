"""
Users VIEW: the JSON shapes the users service sends back.

Salaries are hidden unless the viewer is an admin, the person's manager or
the person; password hashes are never sent.
"""

from datetime import timedelta

from shared.http import response
from shared.users import serialize_user


def user_json(user: dict, viewer: dict) -> dict:
    """One person as the viewer may see them."""
    return serialize_user(user, viewer)


def user_list(result: dict, viewer: dict) -> dict:
    """A page of the people directory."""
    return response(200, {**result, "items": [user_json(row, viewer) for row in result["items"]]})


def user(user_row: dict, viewer: dict, status: int = 200) -> dict:
    """Response with one person."""
    return response(status, user_json(user_row, viewer))


def created(user_row: dict, viewer: dict, employee_id: str, password: str) -> dict:
    """A new account with its one-time password (shown once, never stored in plain text)."""
    return response(201, {"user": user_json(user_row, viewer), "employee_id": employee_id,
                          "temporary_password": password})


def password_reset(user_row: dict, password: str) -> dict:
    """The new one-time password after a reset."""
    return response(200, {"employee_id": user_row["employee_id"], "email": user_row["email"],
                          "temporary_password": password})


def workload(user_id: int, start, max_hours: int, weeks: list[dict], assignments: list[dict]) -> dict:
    """Booked hours per week plus the bookings behind them."""
    this_week = next((w["hours"] for w in weeks if w["week_start"] <= start < w["week_start"] + timedelta(days=7)), 0)
    return response(200, {
        "user_id": user_id,
        "max_hours": max_hours,
        "current_week_hours": this_week,
        "peak_hours": max((w["hours"] for w in weeks), default=0),
        "weeks": [{"week_start": w["week_start"], "hours": w["hours"], "projects": w["projects"]} for w in weeks],
        "assignments": assignments,
    })
