"""
Projects VIEW: the JSON shapes the projects service sends back.

Every project goes out through ``present_project`` so it carries its risk
reasons and cost metrics.
"""

from shared.http import response
from shared.projects import present_project
from shared.schema import PROJECT_STATUSES

AT_RISK_FIELDS = ("id", "code", "name", "status", "end_date", "manager_name", "risk_reasons")


def project(project_row: dict, status: int = 200) -> dict:
    """Response with one project."""
    return response(status, present_project(project_row))


def project_list(result: dict) -> dict:
    """A page of projects."""
    result["items"] = [present_project(row) for row in result["items"]]
    return response(200, result)


def dashboard(user: dict, project_rows: list[dict], upcoming: list[dict], overdue: int, milestones: list[dict],
              max_weekly_hours: int, unread: int, extra: dict) -> dict:
    """Role-specific overview: status counts, risk with reasons, deadlines, budget, then role extras."""
    projects = [present_project(p) for p in project_rows]
    by_status = {s: 0 for s in PROJECT_STATUSES}
    for p in projects:
        by_status[p["status"]] += 1
    at_risk = [{k: p[k] for k in AT_RISK_FIELDS} for p in projects if p["at_risk"]]
    return response(200, {
        "role": user["role"],
        "projects_total": len(projects),
        "projects_by_status": by_status,
        "at_risk_count": len(at_risk),
        "at_risk_projects": at_risk[:10],
        "upcoming_deliverables": upcoming,
        "overdue_deliverables": overdue,
        "upcoming_milestones": milestones,
        "max_weekly_hours": max_weekly_hours,
        "budget": {
            "budget_cents": sum(p["budget_cents"] for p in projects),
            "planned_cents": sum(p["planned_cents"] for p in projects),
            "consumed_cents": sum(p["consumed_cents"] for p in projects),
        },
        "unread_notifications": unread,
        **extra,
    })


def employee_dashboard(assignments: list[dict], today, logged: dict) -> dict:
    """An employee's own bookings, this week's booked hours and this week's logged hours."""
    return {
        "my_assignments": assignments,
        "my_week_hours": sum(a["hours_per_week"] for a in assignments if a["start_date"] <= today <= a["end_date"]),
        "my_logged_this_week": logged,
    }


def summary(project_row: dict, deliverables: dict, members: list[dict], today) -> dict:
    """Deliverable progress, budget burn, team and risk for one project."""
    proj = present_project(project_row)
    deliverables["completion_pct"] = (
        round(100 * deliverables["done"] / deliverables["total"]) if deliverables["total"] else 0
    )
    current = [m for m in members if m["start_date"] <= today <= m["end_date"]]
    budget = proj["budget_cents"]
    return response(200, {
        "project": proj,
        "deliverables": deliverables,
        "team": {
            "size": len({m["user_id"] for m in current}),
            "weekly_hours": sum(m["hours_per_week"] for m in current),
            "members": members,
        },
        "budget": {
            "budget_cents": budget,
            "planned_cents": proj["planned_cents"],
            "consumed_cents": proj["consumed_cents"],
            "remaining_cents": budget - proj["consumed_cents"],
            "consumed_share": proj["consumed_share"],
            "elapsed_share": proj["elapsed_share"],
        },
        "at_risk": proj["at_risk"],
        "risk_reasons": proj["risk_reasons"],
    })
