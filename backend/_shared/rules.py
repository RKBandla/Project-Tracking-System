"""
Business rules that span services.

Weekly capacity: a person can be assigned at most 40 hours per week
(8 hours x 5 days) across all projects that are not archived.
"""

from .errors import conflict

MAX_WEEKLY_HOURS = 40


def allocated_hours(cur, user_id: int, exclude_assignment_id: int | None = None,
                    exclude_project_id: int | None = None) -> int:
    """Sum a user's weekly hours on non-archived projects."""
    cur.execute(
        """
        SELECT COALESCE(SUM(a.hours_per_week), 0) AS hours
        FROM project_assignments a
        JOIN projects p ON p.id = a.project_id
        WHERE a.user_id = %s AND NOT p.is_archived
          AND a.id IS DISTINCT FROM %s AND a.project_id IS DISTINCT FROM %s
        """,
        [user_id, exclude_assignment_id, exclude_project_id],
    )
    return int(cur.fetchone()["hours"])


def check_capacity(cur, user_id: int, requested_hours: int,
                   exclude_assignment_id: int | None = None,
                   exclude_project_id: int | None = None) -> None:
    """
    Raise 409 if adding ``requested_hours`` would exceed the weekly limit.

    The user row is locked first so concurrent assignments cannot both pass.
    """
    cur.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", [user_id])
    current = allocated_hours(cur, user_id, exclude_assignment_id, exclude_project_id)
    if current + requested_hours > MAX_WEEKLY_HOURS:
        remaining = max(MAX_WEEKLY_HOURS - current, 0)
        raise conflict(
            f"Assignment exceeds the {MAX_WEEKLY_HOURS}-hour weekly limit "
            f"({remaining} hours available)",
            {
                "user_id": user_id,
                "allocated_hours": current,
                "requested_hours": requested_hours,
                "remaining_hours": remaining,
                "max_hours": MAX_WEEKLY_HOURS,
            },
        )


def check_reactivation_capacity(cur, project_id: int) -> None:
    """
    Raise 409 if reactivating an archived project would push any assigned
    person over the weekly limit (their hours there start counting again).
    """
    cur.execute(
        "SELECT user_id, hours_per_week FROM project_assignments WHERE project_id = %s ORDER BY user_id",
        [project_id],
    )
    over = []
    for row in cur.fetchall():
        other = allocated_hours(cur, row["user_id"], exclude_project_id=project_id)
        if other + row["hours_per_week"] > MAX_WEEKLY_HOURS:
            over.append({
                "user_id": row["user_id"],
                "allocated_hours": other,
                "project_hours": row["hours_per_week"],
            })
    if over:
        raise conflict(
            "Reactivating would exceed the weekly hour limit for some team members; "
            "reduce their hours first",
            {"over_allocated": over, "max_hours": MAX_WEEKLY_HOURS},
        )
