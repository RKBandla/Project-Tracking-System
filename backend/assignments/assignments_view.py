"""
Assignments VIEW: the JSON shapes the assignments service sends back.

Salary-derived cost (``planned_cents``) is hidden from employees.
"""

from datetime import timedelta

from shared.http import response
from shared.rbac import EMPLOYEE
from shared.rules import MAX_WEEKLY_HOURS


def assignment_json(row: dict, viewer: dict) -> dict:
    """Hide salary-derived cost from employees."""
    if viewer["role"] == EMPLOYEE:
        return {k: v for k, v in row.items() if k != "planned_cents"}
    return row


def assignment_list(result: dict, viewer: dict) -> dict:
    """A page of assignments."""
    result["items"] = [assignment_json(row, viewer) for row in result["items"]]
    return response(200, result)


def assignment(row: dict, viewer: dict, status: int = 200) -> dict:
    """Response with one assignment."""
    return response(status, assignment_json(row, viewer))


def grid(week_starts: list, people: dict, bookings: list[dict]) -> dict:
    """
    Allocation grid: one row per person, one cell per week with the booked hours
    (flagged when at or over 40). Bookings not visible to the viewer are grouped
    as "Other projects".
    """
    rows = []
    over_people = 0
    for person in people["items"]:
        cells = []
        for week_start in week_starts:
            week_end = week_start + timedelta(days=6)
            items: dict = {}
            for b in bookings:
                if b["user_id"] != person["id"] or b["start_date"] > week_end or b["end_date"] < week_start:
                    continue
                key = b["project_id"] if b["visible"] else "other"
                entry = items.setdefault(key, {
                    "project_id": b["project_id"] if b["visible"] else None,
                    "code": b["code"] if b["visible"] else "",
                    "name": b["name"] if b["visible"] else "Other projects",
                    "hours": 0,
                })
                entry["hours"] += b["hours_per_week"]
            hours = sum(i["hours"] for i in items.values())
            cells.append({
                "week_start": week_start,
                "hours": hours,
                "full": hours >= MAX_WEEKLY_HOURS,
                "over": hours > MAX_WEEKLY_HOURS,
                "projects": list(items.values()),
            })
        if any(c["over"] for c in cells):
            over_people += 1
        rows.append({**person, "cells": cells, "peak_hours": max(c["hours"] for c in cells)})

    return response(200, {
        "weeks": week_starts,
        "max_hours": MAX_WEEKLY_HOURS,
        "rows": rows,
        "over_allocated_people": over_people,
        "total": people["total"],
        "page": people["page"],
        "page_size": people["page_size"],
    })
