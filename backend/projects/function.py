"""
Projects service: projects, archiving, health summary and dashboard.

Routes (relative to /api/projects):
    GET  /                  list visible projects (search, filters, sort, pagination)
    POST /                  create project (admin)
    GET  /dashboard         role-specific overview
    GET  /{id}              view project
    PUT  /{id}              update project (admin, or the project's manager)
    POST /{id}/archive      archive project (admin) - projects are never deleted
    POST /{id}/reactivate   reactivate archived project (admin)
    GET  /{id}/summary      deliverable, budget and team metrics

Visibility: admins see all projects, managers the projects they manage and
employees the projects they are assigned to. Employees never see budget data.
"""

from shared import audit
from shared.app import make_handler
from shared.errors import bad_request, conflict, forbidden, not_found
from shared.http import Request, Router, response
from shared.query import Filters, choice_param, date_param, int_param, order_by, paginated
from shared.rbac import (ADMIN, EMPLOYEE, MANAGER, get_project, load_managed_project,
                         load_visible_project, require_role, visible_project_ids)
from shared.projects import insert_project
from shared.rules import MAX_WEEKLY_HOURS, check_reactivation_capacity
from shared.schema import PROJECT_HEALTH, PROJECT_STATUSES
from shared.users import get_user
from shared.validation import Field, check_date_range, validate

router = Router()

PROJECT_SCHEMA = {
    "name": Field(required=True, max_length=200),
    "description": Field(kind="text", max_length=5000),
    "status": Field(choices=PROJECT_STATUSES),
    "health": Field(choices=PROJECT_HEALTH),
    "start_date": Field(kind="date", nullable=True),
    "end_date": Field(kind="date", nullable=True),
    "manager_id": Field(kind="int", nullable=True, min_value=1),
    "budget_total": Field(kind="decimal", min_value=0, max_value=999_999_999_999),
}
BUDGET_FIELDS = ("budget_total",)

LIST_SELECT = """
    SELECT p.id, p.code, p.name, p.description, p.status, p.health, p.start_date, p.end_date,
           p.manager_id, p.budget_total, p.is_archived, p.archived_at, p.created_at, p.updated_at,
           CASE WHEN m.id IS NULL THEN NULL ELSE m.first_name || ' ' || m.last_name END AS manager_name,
           (SELECT count(*) FROM project_assignments a WHERE a.project_id = p.id) AS team_size,
           (SELECT COALESCE(SUM(a.hours_per_week), 0) FROM project_assignments a
             WHERE a.project_id = p.id) AS team_hours,
           (SELECT count(*) FROM deliverables d WHERE d.project_id = p.id) AS deliverable_count,
           (SELECT count(*) FROM deliverables d WHERE d.project_id = p.id AND d.status = 'done')
               AS deliverables_done
    FROM projects p
    LEFT JOIN users m ON m.id = p.manager_id
"""
SORTS = {
    "name": "name", "code": "code", "status": "status", "health": "health",
    "start_date": "start_date", "end_date": "end_date", "budget_total": "budget_total",
    "created_at": "created_at", "updated_at": "updated_at", "manager_name": "manager_name",
}


def _present(project: dict, user: dict) -> dict:
    """Hide budget figures from employees."""
    if user["role"] == EMPLOYEE:
        return {k: v for k, v in project.items() if k not in BUDGET_FIELDS}
    return project


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
    filters.eq("health", choice_param(q, "health", PROJECT_HEALTH))
    filters.eq("manager_id", int_param(q, "manager_id"))
    start_from = date_param(q, "start_from")
    if start_from:
        filters.add("start_date >= %s", start_from)
    end_to = date_param(q, "end_to")
    if end_to:
        filters.add("end_date <= %s", end_to)
    result = paginated(cur, LIST_SELECT, filters, order_by(q, SORTS, "name"), q)
    result["items"] = [_present(row, user) for row in result["items"]]
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
    audit.record(cur, user["id"], "project", project_id, "create", data)
    return response(201, get_project(cur, project_id))


@router.get("/dashboard")
def dashboard(request: Request, cur) -> dict:
    """Role-specific overview of projects, deliverables, capacity and requests."""
    user = request.user
    scope = _scope(user, Filters(clauses=["NOT is_archived"]))
    where, params = scope.where(), scope.params

    cur.execute(f"SELECT status, count(*) AS n FROM projects {where} GROUP BY status", params)  # nosec B608
    by_status = {s: 0 for s in PROJECT_STATUSES} | {r["status"]: r["n"] for r in cur.fetchall()}
    cur.execute(f"SELECT health, count(*) AS n FROM projects {where} GROUP BY health", params)  # nosec B608
    by_health = {h: 0 for h in PROJECT_HEALTH} | {r["health"]: r["n"] for r in cur.fetchall()}

    cur.execute(
        f"""SELECT id, code, name, status, health, end_date FROM projects {where}
            AND health IN ('red', 'amber') ORDER BY health DESC, end_date NULLS LAST LIMIT 5""",  # nosec B608
        params,
    )
    at_risk = cur.fetchall()

    deliverable_scope = f"d.project_id IN (SELECT id FROM projects {where})"  # nosec B608
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
        "projects_total": sum(by_status.values()),
        "projects_by_status": by_status,
        "projects_by_health": by_health,
        "at_risk_projects": at_risk,
        "upcoming_deliverables": upcoming,
        "overdue_deliverables": overdue,
        "max_weekly_hours": MAX_WEEKLY_HOURS,
    }

    if user["role"] in (ADMIN, MANAGER):
        cur.execute(
            f"""SELECT COALESCE(SUM(budget_total), 0) AS budget_total,
                       COALESCE((SELECT SUM(b.planned_amount) FROM budget_items b
                                  WHERE b.project_id IN (SELECT id FROM projects {where})), 0) AS planned,
                       COALESCE((SELECT SUM(b.actual_amount) FROM budget_items b
                                  WHERE b.project_id IN (SELECT id FROM projects {where})), 0) AS actual
                FROM projects {where}""",  # nosec B608
            params * 3,
        )
        result["budget"] = cur.fetchone()
        capacity_where = "u.is_active AND u.role <> 'admin'"
        capacity_params: list = []
        if user["role"] == MANAGER:
            capacity_where += " AND u.manager_id = %s"
            capacity_params.append(user["id"])
        cur.execute(
            f"""SELECT u.id, u.employee_id, u.first_name || ' ' || u.last_name AS full_name, u.job_title,
                       (SELECT COALESCE(SUM(a.hours_per_week), 0) FROM project_assignments a
                          JOIN projects p ON p.id = a.project_id
                         WHERE a.user_id = u.id AND NOT p.is_archived) AS allocated_hours
                FROM users u WHERE {capacity_where}
                ORDER BY allocated_hours DESC, u.last_name""",  # nosec B608
            capacity_params,
        )
        people = cur.fetchall()
        result["capacity"] = {
            "people": len(people),
            "fully_allocated": sum(1 for p in people if p["allocated_hours"] >= MAX_WEEKLY_HOURS),
            "available_hours": sum(max(MAX_WEEKLY_HOURS - p["allocated_hours"], 0) for p in people),
            "team": people[:15],
        }
        if user["role"] == ADMIN:
            cur.execute("SELECT count(*) AS n FROM project_requests WHERE status = 'pending'")
            result["pending_requests"] = cur.fetchone()["n"]
            cur.execute("SELECT count(*) AS n FROM projects WHERE is_archived")
            result["archived_projects"] = cur.fetchone()["n"]
        else:
            cur.execute("SELECT count(*) AS n FROM project_requests WHERE status = 'pending' AND requested_by = %s",
                        [user["id"]])
            result["pending_requests"] = cur.fetchone()["n"]
    else:
        cur.execute(
            """SELECT a.project_id, p.code AS project_code, p.name AS project_name, p.status, p.health,
                      a.project_role, a.hours_per_week
               FROM project_assignments a JOIN projects p ON p.id = a.project_id
               WHERE a.user_id = %s AND NOT p.is_archived ORDER BY p.name""",
            [user["id"]],
        )
        assignments = cur.fetchall()
        hours = sum(a["hours_per_week"] for a in assignments)
        result["my_assignments"] = assignments
        result["my_hours"] = {"allocated": hours, "remaining": max(MAX_WEEKLY_HOURS - hours, 0)}

    return response(200, result)


@router.get("/{id}")
def get_one(request: Request, cur) -> dict:
    """View a project."""
    project = load_visible_project(cur, request.user, request.params["id"])
    return response(200, _present(project, request.user))


@router.put("/{id}")
def update_project(request: Request, cur) -> dict:
    """Update a project (admin, or its manager for everything except the manager)."""
    user = request.user
    project = load_managed_project(cur, user, request.params["id"])
    data = validate(request.body, PROJECT_SCHEMA, partial=True)
    if not data:
        raise bad_request("Nothing to update")
    for required in ("name", "status", "health", "budget_total"):
        if required in data and data[required] is None:
            raise bad_request("Validation failed", {required: "is required"})
    if "manager_id" in data and data["manager_id"] != project["manager_id"]:
        if user["role"] != ADMIN:
            raise forbidden("Only admins can assign a project's manager")
        _check_manager(cur, data["manager_id"])
    check_date_range(data.get("start_date", project["start_date"]), data.get("end_date", project["end_date"]))
    changes = audit.diff(project, data)
    if changes:
        assignments = ", ".join(f"{name} = %s" for name in data)
        cur.execute(f"UPDATE projects SET {assignments}, updated_at = now() WHERE id = %s",  # nosec B608
                    [*data.values(), project["id"]])
        audit.record(cur, user["id"], "project", project["id"], "update", changes)
    return response(200, get_project(cur, project["id"]))


@router.post("/{id}/archive")
def archive(request: Request, cur) -> dict:
    """Archive a project (admin only). Records are kept and can be reactivated."""
    require_role(request.user, ADMIN)
    project = get_project(cur, request.params["id"], lock=True)
    if project is None:
        raise not_found("Project")
    if project["is_archived"]:
        raise conflict("Project is already archived")
    cur.execute(
        "UPDATE projects SET is_archived = TRUE, archived_at = now(), archived_by = %s, updated_at = now() "
        "WHERE id = %s",
        [request.user["id"], project["id"]],
    )
    audit.record(cur, request.user["id"], "project", project["id"], "archive")
    return response(200, get_project(cur, project["id"]))


@router.post("/{id}/reactivate")
def reactivate(request: Request, cur) -> dict:
    """Reactivate an archived project (admin only)."""
    require_role(request.user, ADMIN)
    project = get_project(cur, request.params["id"], lock=True)
    if project is None:
        raise not_found("Project")
    if not project["is_archived"]:
        raise conflict("Project is not archived")
    check_reactivation_capacity(cur, project["id"])
    cur.execute(
        "UPDATE projects SET is_archived = FALSE, archived_at = NULL, archived_by = NULL, updated_at = now() "
        "WHERE id = %s",
        [project["id"]],
    )
    audit.record(cur, request.user["id"], "project", project["id"], "reactivate")
    return response(200, get_project(cur, project["id"]))


@router.get("/{id}/summary")
def summary(request: Request, cur) -> dict:
    """Deliverable progress, budget burn and team allocation for one project."""
    user = request.user
    project = load_visible_project(cur, user, request.params["id"])
    pid = project["id"]

    cur.execute(
        """SELECT count(*) AS total,
                  count(*) FILTER (WHERE status = 'todo') AS todo,
                  count(*) FILTER (WHERE status = 'in_progress') AS in_progress,
                  count(*) FILTER (WHERE status = 'blocked') AS blocked,
                  count(*) FILTER (WHERE status = 'done') AS done,
                  count(*) FILTER (WHERE status <> 'done' AND due_date < CURRENT_DATE) AS overdue,
                  COALESCE(ROUND(AVG(progress_pct)), 0) AS avg_progress
           FROM deliverables WHERE project_id = %s""",
        [pid],
    )
    deliverables = cur.fetchone()
    deliverables["completion_pct"] = (
        round(100 * deliverables["done"] / deliverables["total"]) if deliverables["total"] else 0
    )

    cur.execute(
        """SELECT a.id, a.user_id, u.employee_id, u.first_name || ' ' || u.last_name AS full_name,
                  u.job_title, a.project_role, a.hours_per_week
           FROM project_assignments a JOIN users u ON u.id = a.user_id
           WHERE a.project_id = %s ORDER BY u.last_name""",
        [pid],
    )
    members = cur.fetchall()
    result = {
        "project": _present(project, user),
        "deliverables": deliverables,
        "team": {
            "size": len(members),
            "total_hours": sum(m["hours_per_week"] for m in members),
            "members": members,
        },
    }

    if user["role"] != EMPLOYEE:
        cur.execute(
            """SELECT COALESCE(SUM(planned_amount), 0) AS planned, COALESCE(SUM(actual_amount), 0) AS actual
               FROM budget_items WHERE project_id = %s""",
            [pid],
        )
        budget = cur.fetchone()
        total = project["budget_total"]
        budget["budget_total"] = total
        budget["remaining"] = total - budget["actual"]
        budget["burn_pct"] = round(float(100 * budget["actual"] / total), 1) if total else 0
        result["budget"] = budget

    return response(200, result)


handler = make_handler(router, "projects")
