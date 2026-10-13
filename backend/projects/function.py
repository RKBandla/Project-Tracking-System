"""
Projects service: projects, archiving, health summary and dashboard.

Routes (relative to /api/projects):
    GET  /                  list visible projects (search, filters, sort, pagination)
    POST /                  create project (admin)
    GET  /dashboard         role-specific overview
    GET  /{id}              view project (with cost and risk metrics)
    PUT  /{id}              update (admin: all fields; manager: description and status)
    POST /{id}/archive      archive project (admin) - nothing is ever deleted
    POST /{id}/reactivate   reactivate archived project (admin)
    GET  /{id}/summary      deliverable, budget, team and risk metrics

Visibility: admins see all projects, managers the projects they manage and
employees the projects they are assigned to.
"""

from shared import audit
from shared.app import make_handler
from shared.errors import bad_request, conflict, forbidden, not_found
from shared.http import Request, Router, response
from shared.projects import PROJECT_SELECT, get_project, insert_project, present_project
from shared.query import Filters, choice_param, date_param, int_param, order_by, paginated
from shared.rbac import (ADMIN, EMPLOYEE, MANAGER, load_managed_project, load_visible_project,
                         require_role, visible_project_ids)
from shared.rules import MAX_WEEKLY_HOURS, assert_within_capacity, lock_user
from shared.schema import PROJECT_STATUSES
from shared.users import get_user
from shared.validation import Field, check_date_range, validate

router = Router()

PROJECT_SCHEMA = {
    "name": Field(required=True, max_length=200),
    "description": Field(kind="text", max_length=5000),
    "status": Field(choices=PROJECT_STATUSES),
    "start_date": Field(kind="date", nullable=True),
    "end_date": Field(kind="date", nullable=True),
    "manager_id": Field(kind="int", nullable=True, min_value=1),
    "budget_cents": Field(kind="int", min_value=0, max_value=10**14),
}
MANAGER_EDITABLE = ("description", "status")

SORTS = {
    "name": "name", "code": "code", "status": "status", "start_date": "start_date",
    "end_date": "end_date", "budget_cents": "budget_cents", "consumed_cents": "consumed_cents",
    "created_at": "created_at", "updated_at": "updated_at", "manager_name": "manager_name",
}


def _check_manager(cur, manager_id: int | None) -> None:
    """A project manager must be an active manager or admin."""
    if manager_id is None:
        return
    manager = get_user(cur, manager_id)
    if manager is None or not manager["is_active"] or manager["role"] not in (ADMIN, MANAGER):
        raise bad_request("Validation failed", {"manager_id": "must be an active manager or admin"})


def _scope(user: dict, filters: Filters, column: str = "id") -> Filters:
    """Restrict a query to projects the user may view."""
    visible = visible_project_ids(user)
    if visible is not None:
        sql, params = visible
        filters.add(f"{column} IN ({sql})", *params)
    return filters


def _label(project: dict) -> str:
    """'PRJ-0001 Apollo' for audit summaries."""
    return f"{project['code']} {project['name']}"


def _today(cur):
    """The database's current date (keeps 'today' consistent with SQL comparisons)."""
    cur.execute("SELECT CURRENT_DATE AS d")
    return cur.fetchone()["d"]


@router.get("/")
def list_projects(request: Request, cur) -> dict:
    """List projects visible to the caller."""
    user, q = request.user, request.query
    filters = _scope(user, Filters())
    archived = choice_param(q, "archived", ("true", "false", "all")) or "false"
    if archived != "all":
        filters.eq("is_archived", archived == "true")
    filters.search(["name", "code", "description", "manager_name"], q.get("q"))
    filters.eq("status", choice_param(q, "status", PROJECT_STATUSES))
    risk = choice_param(q, "at_risk", ("true", "false"))
    if risk is not None:
        filters.eq("at_risk", risk == "true")
    filters.eq("manager_id", int_param(q, "manager_id"))
    start_from = date_param(q, "start_from")
    if start_from:
        filters.add("start_date >= %s", start_from)
    end_to = date_param(q, "end_to")
    if end_to:
        filters.add("end_date <= %s", end_to)
    result = paginated(cur, PROJECT_SELECT, filters, order_by(q, SORTS, "name"), q)
    result["items"] = [present_project(row) for row in result["items"]]
    return response(200, result)


@router.post("/")
def create_project(request: Request, cur) -> dict:
    """Create a project (admin only; managers submit a project request instead)."""
    user = request.user
    if user["role"] != ADMIN:
        raise forbidden("Only admins can create projects; managers can submit a project request")
    data = validate(request.body, PROJECT_SCHEMA)
    check_date_range(data["start_date"], data["end_date"])
    _check_manager(cur, data["manager_id"])
    project_id = insert_project(cur, user["id"], data)
    project = get_project(cur, project_id)
    audit.record(cur, user, "project", project_id, "create", f"created project {_label(project)}", data)
    return response(201, present_project(project))


@router.get("/dashboard")
def dashboard(request: Request, cur) -> dict:
    """Role-specific overview: status, risk with reasons, deadlines, capacity, approvals."""
    user = request.user
    scope = _scope(user, Filters(clauses=["NOT is_archived"]))
    where, params = scope.where(), scope.params

    cur.execute(
        f"SELECT * FROM ({PROJECT_SELECT}) AS pr {where} "  # nosec B608
        "ORDER BY at_risk DESC, end_date NULLS LAST, name",
        params,
    )
    projects = [present_project(p) for p in cur.fetchall()]
    by_status = {s: 0 for s in PROJECT_STATUSES}
    for p in projects:
        by_status[p["status"]] += 1
    at_risk = [
        {k: p[k] for k in ("id", "code", "name", "status", "end_date", "manager_name", "risk_reasons")}
        for p in projects if p["at_risk"]
    ]

    deliverable_scope = f"d.project_id IN (SELECT id FROM projects {where}) AND NOT d.is_archived"  # nosec B608
    deliverable_params = list(params)
    if user["role"] == EMPLOYEE:
        deliverable_scope += " AND d.assignee_id = %s"
        deliverable_params.append(user["id"])
    cur.execute(
        f"""SELECT d.id, d.title, d.status, d.due_date, d.progress_pct, d.project_id,
                   p.code AS project_code, p.name AS project_name
            FROM deliverables d JOIN projects p ON p.id = d.project_id
            WHERE {deliverable_scope} AND d.status <> 'done' AND d.due_date IS NOT NULL
              AND d.due_date <= CURRENT_DATE + 14
            ORDER BY d.due_date LIMIT 10""",  # nosec B608
        deliverable_params,
    )
    upcoming = cur.fetchall()
    cur.execute(
        f"""SELECT count(*) AS n FROM deliverables d WHERE {deliverable_scope}
            AND d.status <> 'done' AND d.due_date < CURRENT_DATE""",  # nosec B608
        deliverable_params,
    )
    overdue = cur.fetchone()["n"]

    result = {
        "role": user["role"],
        "projects_total": len(projects),
        "projects_by_status": by_status,
        "at_risk_count": len(at_risk),
        "at_risk_projects": at_risk[:10],
        "upcoming_deliverables": upcoming,
        "overdue_deliverables": overdue,
        "max_weekly_hours": MAX_WEEKLY_HOURS,
        "budget": {
            "budget_cents": sum(p["budget_cents"] for p in projects),
            "planned_cents": sum(p["planned_cents"] for p in projects),
            "consumed_cents": sum(p["consumed_cents"] for p in projects),
        },
    }

    cur.execute("SELECT count(*) AS n FROM notifications WHERE user_id = %s AND read_at IS NULL", [user["id"]])
    result["unread_notifications"] = cur.fetchone()["n"]

    if user["role"] in (ADMIN, MANAGER):
        # People booked to the 40-hour limit in any of the next 8 weeks
        cur.execute(
            """
            WITH weeks AS (
                SELECT generate_series(date_trunc('week', CURRENT_DATE),
                                       date_trunc('week', CURRENT_DATE) + interval '7 weeks',
                                       interval '1 week')::date AS week_start
            ), load AS (
                SELECT a.user_id, w.week_start, SUM(a.hours_per_week) AS hours
                FROM weeks w
                JOIN project_assignments a ON NOT a.is_archived
                     AND a.start_date <= w.week_start + 6 AND a.end_date >= w.week_start
                JOIN projects p ON p.id = a.project_id AND NOT p.is_archived
                GROUP BY a.user_id, w.week_start
            )
            SELECT u.id, u.first_name || ' ' || u.last_name AS full_name, u.job_title,
                   MAX(l.hours)::int AS peak_hours
            FROM load l JOIN users u ON u.id = l.user_id
            GROUP BY u.id HAVING MAX(l.hours) >= %s
            ORDER BY full_name LIMIT 20
            """,
            [MAX_WEEKLY_HOURS],
        )
        result["fully_booked_people"] = cur.fetchall()
        if user["role"] == ADMIN:
            cur.execute("SELECT count(*) AS n FROM project_requests WHERE status = 'pending'")
            result["pending_requests"] = cur.fetchone()["n"]
            cur.execute("SELECT count(*) AS n FROM time_entries WHERE status = 'pending'")
        else:
            cur.execute("SELECT count(*) AS n FROM project_requests WHERE status = 'pending' AND requested_by = %s",
                        [user["id"]])
            result["pending_requests"] = cur.fetchone()["n"]
            cur.execute(
                "SELECT count(*) AS n FROM time_entries t JOIN users u ON u.id = t.user_id "
                "WHERE t.status = 'pending' AND u.manager_id = %s",
                [user["id"]],
            )
        result["hours_to_approve"] = cur.fetchone()["n"]
    else:
        today = _today(cur)
        cur.execute(
            """SELECT a.id, a.project_id, p.code AS project_code, p.name AS project_name,
                      a.project_role, a.hours_per_week, a.start_date, a.end_date
               FROM project_assignments a JOIN projects p ON p.id = a.project_id
               WHERE a.user_id = %s AND NOT a.is_archived AND NOT p.is_archived AND a.end_date >= %s
               ORDER BY a.start_date, p.name""",
            [user["id"], today],
        )
        assignments = cur.fetchall()
        result["my_assignments"] = assignments
        result["my_week_hours"] = sum(
            a["hours_per_week"] for a in assignments if a["start_date"] <= today <= a["end_date"]
        )
        cur.execute(
            """SELECT COALESCE(SUM(hours) FILTER (WHERE status = 'pending'), 0) AS pending,
                      COALESCE(SUM(hours) FILTER (WHERE status = 'approved'), 0) AS approved
               FROM time_entries WHERE user_id = %s AND work_date >= date_trunc('week', CURRENT_DATE)""",
            [user["id"]],
        )
        result["my_logged_this_week"] = cur.fetchone()

    return response(200, result)


@router.get("/{id}")
def get_one(request: Request, cur) -> dict:
    """View a project."""
    project = load_visible_project(cur, request.user, request.params["id"])
    return response(200, present_project(project))


@router.put("/{id}")
def update_project(request: Request, cur) -> dict:
    """Update a project: admins any field, the project's manager only description and status."""
    user = request.user
    project = load_managed_project(cur, user, request.params["id"])
    body = request.body
    if user["role"] != ADMIN and set(body) - set(MANAGER_EDITABLE):
        raise forbidden("Managers can only change a project's description and status")
    data = validate(body, PROJECT_SCHEMA, partial=True)
    if not data:
        raise bad_request("Nothing to update")
    for required in ("name", "status", "budget_cents"):
        if required in data and data[required] is None:
            raise bad_request("Validation failed", {required: "is required"})
    if "description" in data and data["description"] is None:
        data["description"] = ""
    if "manager_id" in data and data["manager_id"] != project["manager_id"]:
        _check_manager(cur, data["manager_id"])
    check_date_range(data.get("start_date", project["start_date"]), data.get("end_date", project["end_date"]))
    changes = audit.diff(project, data)
    if changes:
        assignments = ", ".join(f"{name} = %s" for name in data)
        cur.execute(f"UPDATE projects SET {assignments}, updated_at = now() WHERE id = %s",  # nosec B608
                    [*data.values(), project["id"]])
        audit.record(cur, user, "project", project["id"], "update",
                     f"updated project {_label(project)} ({', '.join(sorted(changes))})", changes)
    return response(200, present_project(get_project(cur, project["id"])))


@router.post("/{id}/archive")
def archive(request: Request, cur) -> dict:
    """Archive a project (admin only). Records are kept and can be reactivated."""
    user = request.user
    require_role(user, ADMIN)
    project = get_project(cur, request.params["id"], lock=True)
    if project is None:
        raise not_found("Project")
    if project["is_archived"]:
        raise conflict("Project is already archived")
    cur.execute(
        "UPDATE projects SET is_archived = TRUE, archived_at = now(), archived_by = %s, updated_at = now() "
        "WHERE id = %s",
        [user["id"], project["id"]],
    )
    audit.record(cur, user, "project", project["id"], "archive", f"archived project {_label(project)}")
    return response(200, present_project(get_project(cur, project["id"])))


@router.post("/{id}/reactivate")
def reactivate(request: Request, cur) -> dict:
    """Reactivate an archived project (admin). Team bookings must still fit in 40 h/week."""
    user = request.user
    require_role(user, ADMIN)
    project = get_project(cur, request.params["id"], lock=True)
    if project is None:
        raise not_found("Project")
    if not project["is_archived"]:
        raise conflict("Project is not archived")
    cur.execute(
        "UPDATE projects SET is_archived = FALSE, archived_at = NULL, archived_by = NULL, updated_at = now() "
        "WHERE id = %s",
        [project["id"]],
    )
    cur.execute(
        """SELECT user_id, MIN(start_date) AS start_date, MAX(end_date) AS end_date
           FROM project_assignments WHERE project_id = %s AND NOT is_archived
           GROUP BY user_id ORDER BY user_id""",
        [project["id"]],
    )
    for booking in cur.fetchall():
        lock_user(cur, booking["user_id"])
        assert_within_capacity(cur, booking["user_id"], booking["start_date"], booking["end_date"])
    audit.record(cur, user, "project", project["id"], "update", f"reactivated project {_label(project)}")
    return response(200, present_project(get_project(cur, project["id"])))


@router.get("/{id}/summary")
def summary(request: Request, cur) -> dict:
    """Deliverable progress, budget burn, team and risk for one project."""
    user = request.user
    project = present_project(load_visible_project(cur, user, request.params["id"]))
    pid = project["id"]

    cur.execute(
        """SELECT count(*) AS total,
                  count(*) FILTER (WHERE status = 'todo') AS todo,
                  count(*) FILTER (WHERE status = 'in_progress') AS in_progress,
                  count(*) FILTER (WHERE status = 'blocked') AS blocked,
                  count(*) FILTER (WHERE status = 'done') AS done,
                  count(*) FILTER (WHERE status <> 'done' AND due_date < CURRENT_DATE) AS overdue
           FROM deliverables WHERE project_id = %s AND NOT is_archived""",
        [pid],
    )
    deliverables = cur.fetchone()
    deliverables["completion_pct"] = (
        round(100 * deliverables["done"] / deliverables["total"]) if deliverables["total"] else 0
    )

    cur.execute(
        """SELECT a.id, a.user_id, u.employee_id, u.first_name || ' ' || u.last_name AS full_name,
                  u.job_title, a.project_role, a.hours_per_week, a.start_date, a.end_date
           FROM project_assignments a JOIN users u ON u.id = a.user_id
           WHERE a.project_id = %s AND NOT a.is_archived ORDER BY u.last_name, a.start_date""",
        [pid],
    )
    members = cur.fetchall()
    today = _today(cur)
    current = [m for m in members if m["start_date"] <= today <= m["end_date"]]

    budget = project["budget_cents"]
    return response(200, {
        "project": project,
        "deliverables": deliverables,
        "team": {
            "size": len({m["user_id"] for m in current}),
            "weekly_hours": sum(m["hours_per_week"] for m in current),
            "members": members,
        },
        "budget": {
            "budget_cents": budget,
            "planned_cents": project["planned_cents"],
            "consumed_cents": project["consumed_cents"],
            "remaining_cents": budget - project["consumed_cents"],
            "consumed_share": project["consumed_share"],
            "elapsed_share": project["elapsed_share"],
        },
        "at_risk": project["at_risk"],
        "risk_reasons": project["risk_reasons"],
    })


handler = make_handler(router, "projects")
