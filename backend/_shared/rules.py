"""
Business rules that span services.

Weekly capacity: nobody is booked over 40 hours in any calendar week
(Monday-Sunday) across all non-archived assignments on non-archived projects.
The check runs *after* a change inside the same transaction, so a violation
rolls the change back, and the person's row is locked first so concurrent
bookings cannot both pass.
"""

from datetime import date

from .errors import conflict

MAX_WEEKLY_HOURS = 40

_WEEKLY_LOAD_SQL = """
    WITH weeks AS (
        SELECT generate_series(date_trunc('week', %(start)s::date), date_trunc('week', %(end)s::date),
                               interval '1 week')::date AS week_start
    )
    SELECT w.week_start,
           SUM(a.hours_per_week)::int AS hours,
           json_agg(json_build_object('project_id', p.id, 'code', p.code, 'name', p.name,
                                      'hours', a.hours_per_week) ORDER BY p.code) AS projects
    FROM weeks w
    JOIN project_assignments a
      ON a.user_id = %(user_id)s AND NOT a.is_archived
     AND a.start_date <= w.week_start + 6 AND a.end_date >= w.week_start
    JOIN projects p ON p.id = a.project_id AND NOT p.is_archived
    GROUP BY w.week_start
"""


def lock_user(cur, user_id: int) -> None:
    """Serialise capacity changes for one person."""
    cur.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", [user_id])


def weekly_load(cur, user_id: int, start: date, end: date) -> list[dict]:
    """Booked hours per week (only weeks with any booking) between two dates."""
    cur.execute(_WEEKLY_LOAD_SQL + " ORDER BY w.week_start",  # nosec B608 - constant SQL
                {"user_id": user_id, "start": start, "end": end})
    return cur.fetchall()


def assert_within_capacity(cur, user_id: int, start: date, end: date) -> None:
    """
    Raise 409 naming the conflicting projects if any week between ``start`` and
    ``end`` is booked over the limit. Call after inserting or changing assignments.
    """
    cur.execute(
        _WEEKLY_LOAD_SQL + " HAVING SUM(a.hours_per_week) > %(max)s ORDER BY w.week_start",  # nosec B608
        {"user_id": user_id, "start": start, "end": end, "max": MAX_WEEKLY_HOURS},
    )
    over = cur.fetchall()
    if not over:
        return
    first = over[0]
    conflicting = {}
    for week in over:
        for project in week["projects"]:
            conflicting[project["project_id"]] = {k: project[k] for k in ("project_id", "code", "name")}
    names = ", ".join(f"{p['code']} {p['name']}" for p in conflicting.values())
    raise conflict(
        f"Booking exceeds {MAX_WEEKLY_HOURS} hours in the week of {first['week_start'].isoformat()} "
        f"({first['hours']} h booked across {names})",
        {
            "user_id": user_id,
            "max_hours": MAX_WEEKLY_HOURS,
            "weeks": [{"week_start": w["week_start"].isoformat(), "booked_hours": w["hours"],
                       "projects": w["projects"]} for w in over],
            "conflicting_projects": list(conflicting.values()),
        },
    )
