"""
Timesheets VIEW: the JSON shapes the timesheets service sends back.

Pending and approved hours count towards daily and weekly totals;
withdrawn and rejected entries are shown but not counted.
"""

from datetime import timedelta
from decimal import Decimal

from shared.http import response

COUNTED = ("pending", "approved")


def entry(row: dict, status: int = 200) -> dict:
    """Response with one time entry."""
    return response(status, row)


def entry_list(result: dict, total_hours: Decimal) -> dict:
    """A page of time entries plus the total hours across all pages."""
    return response(200, {**result, "total_hours": total_hours})


def approved_batch(entries: list[dict]) -> dict:
    """The entries approved in one batch."""
    return response(200, {"approved": entries})


def week(start, end, bookings: list[dict], entries: list[dict]) -> dict:
    """A timesheet week: bookings, entries, daily totals and weekly totals."""
    days = []
    for i in range(7):
        day = start + timedelta(days=i)
        counted = [e for e in entries if e["work_date"] == day and e["status"] in COUNTED]
        days.append({"date": day, "hours": sum((e["hours"] for e in counted), Decimal(0))})
    counted = [e for e in entries if e["status"] in COUNTED]
    return response(200, {
        "week_start": start,
        "week_end": end,
        "bookings": bookings,
        "entries": entries,
        "days": days,
        "booked_hours": sum(b["hours_per_week"] for b in bookings),
        "logged_hours": sum((e["hours"] for e in counted), Decimal(0)),
        "approved_hours": sum((e["hours"] for e in entries if e["status"] == "approved"), Decimal(0)),
    })
