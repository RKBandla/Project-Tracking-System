"""
Projects CONTROLLER: the routes for projects and the dashboard.

Each route reads the request, checks permissions and rules, calls the model
(projects_model) for data and returns a view (projects_view).

Visibility: admins see all projects, managers the projects they manage and
employees the projects they are assigned to.
"""

import projects_model as model
import projects_view as view
from shared import audit
from shared.errors import bad_request, conflict, forbidden, not_found
from shared.http import Request, Router
from shared.query import Filters, choice_param, date_param, int_param, order_by
from shared.rbac import (ADMIN, EMPLOYEE, MANAGER, load_managed_project, load_visible_project,
                         require_role, visible_project_ids)
from shared.rules import MAX_WEEKLY_HOURS, assert_within_capacity, lock_user
from shared.schema import PROJECT_STATUSES
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


def _check_manager(cur, manager_id: int | None) -> None:
    """A project manager must be an active manager or admin."""
    if manager_id is None:
        return
    manager = model.get_user(cur, manager_id)
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


def _load_for_admin(cur, project_id: int) -> dict:
    """Fetch and lock a project or raise 404."""
    project = model.get_project(cur, project_id, lock=True)
    if project is None:
        raise not_found("Project")
    return project


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
    return view.project_list(model.list_projects(cur, filters, order_by(q, model.SORTS, "name"), q))


@router.post("/")
def create_project(request: Request, cur) -> dict:
    """Create a project (admin only; managers submit a project request instead)."""
    user = request.user
    if user["role"] != ADMIN:
        raise forbidden("Only admins can create projects; managers can submit a project request")
    data = validate(request.body, PROJECT_SCHEMA)
    check_date_range(data["start_date"], data["end_date"])
    _check_manager(cur, data["manager_id"])
    project_id = model.insert_project(cur, user["id"], data)
    project = model.get_project(cur, project_id)
    audit.record(cur, user, "project", project_id, "create", f"created project {_label(project)}", data)
    return view.project(project, 201)


@router.get("/dashboard")
def dashboard(request: Request, cur) -> dict:
    """Role-specific overview: status, risk with reasons, deadlines, capacity, approvals."""
    user = request.user
    scope = _scope(user, Filters(clauses=["NOT is_archived"]))
    where, params = scope.where(), scope.params

    projects = model.dashboard_projects(cur, where, params)
    deliverable_scope, deliverable_params = model.deliverable_scope(
        where, params, user["id"] if user["role"] == EMPLOYEE else None)
    upcoming = model.upcoming_deliverables(cur, deliverable_scope, deliverable_params)
    overdue = model.overdue_deliverable_count(cur, deliverable_scope, deliverable_params)
    milestones = model.upcoming_milestones(cur, where, params)
    unread = model.unread_notification_count(cur, user["id"])

    if user["role"] in (ADMIN, MANAGER):
        extra = {"fully_booked_people": model.fully_booked_people(cur, MAX_WEEKLY_HOURS)}
        if user["role"] == ADMIN:
            extra["pending_requests"] = model.pending_request_count(cur)
            extra["hours_to_approve"] = model.pending_hours_count(cur)
        else:
            extra["pending_requests"] = model.pending_request_count(cur, user["id"])
            extra["hours_to_approve"] = model.pending_hours_count(cur, user["id"])
    else:
        today = model.today(cur)
        extra = view.employee_dashboard(model.active_assignments(cur, user["id"], today), today,
                                        model.logged_this_week(cur, user["id"]))

    return view.dashboard(user, projects, upcoming, overdue, milestones, MAX_WEEKLY_HOURS, unread, extra)


@router.get("/{id}")
def get_one(request: Request, cur) -> dict:
    """View a project."""
    return view.project(load_visible_project(cur, request.user, request.params["id"]))


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
        model.update_project(cur, project["id"], data)
        audit.record(cur, user, "project", project["id"], "update",
                     f"updated project {_label(project)} ({', '.join(sorted(changes))})", changes)
    return view.project(model.get_project(cur, project["id"]))


@router.post("/{id}/archive")
def archive(request: Request, cur) -> dict:
    """Archive a project (admin only). Records are kept and can be reactivated."""
    user = request.user
    require_role(user, ADMIN)
    project = _load_for_admin(cur, request.params["id"])
    if project["is_archived"]:
        raise conflict("Project is already archived")
    model.archive_project(cur, project["id"], user["id"])
    audit.record(cur, user, "project", project["id"], "archive", f"archived project {_label(project)}")
    return view.project(model.get_project(cur, project["id"]))


@router.post("/{id}/reactivate")
def reactivate(request: Request, cur) -> dict:
    """Reactivate an archived project (admin). Team bookings must still fit in 40 h/week."""
    user = request.user
    require_role(user, ADMIN)
    project = _load_for_admin(cur, request.params["id"])
    if not project["is_archived"]:
        raise conflict("Project is not archived")
    model.reactivate_project(cur, project["id"])
    for booking in model.team_bookings(cur, project["id"]):
        lock_user(cur, booking["user_id"])
        assert_within_capacity(cur, booking["user_id"], booking["start_date"], booking["end_date"])
    audit.record(cur, user, "project", project["id"], "update", f"reactivated project {_label(project)}")
    return view.project(model.get_project(cur, project["id"]))


@router.get("/{id}/summary")
def summary(request: Request, cur) -> dict:
    """Deliverable progress, budget burn, team and risk for one project."""
    project = load_visible_project(cur, request.user, request.params["id"])
    pid = project["id"]
    deliverables = model.deliverable_counts(cur, pid)
    members = model.team_members(cur, pid)
    return view.summary(project, deliverables, members, model.today(cur))
