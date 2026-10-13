"""
Budgets service: one budget per project, compared with planned and consumed cost.

    hourly rate   = annual salary / 2080
    planned cost  = sum(hours per week x weeks in assignment x hourly rate)
    consumed cost = sum(approved logged hours x hourly rate)

Routes (relative to /api/budgets):
    GET /         budgets of visible projects (search, at-risk filter, pagination)
    GET /{id}     one project's budget, with per-person breakdown for admins and its manager
    PUT /{id}     set the budget {budget_cents} (admin, or the project's manager)

All amounts are whole cents. Employees see totals for projects they are assigned
to, but never per-person costs (they reveal salaries).
"""

from shared import audit
from shared.app import make_handler
from shared.errors import bad_request
from shared.http import Request, Router, response
from shared.projects import CONSUMED_COST_SQL, PLANNED_COST_SQL, PROJECT_SELECT, get_project, present_project
from shared.query import Filters, choice_param, order_by, paginated
from shared.rbac import can_manage_project, load_managed_project, load_visible_project, visible_project_ids
from shared.validation import Field, validate

router = Router()

BUDGET_SCHEMA = {"budget_cents": Field(kind="int", required=True, min_value=0, max_value=10**14)}
SORTS = {"name": "name", "code": "code", "budget_cents": "budget_cents", "planned_cents": "planned_cents",
         "consumed_cents": "consumed_cents", "end_date": "end_date"}
FIELDS = ("id", "code", "name", "status", "start_date", "end_date", "manager_id", "manager_name", "is_archived",
          "budget_cents", "planned_cents", "consumed_cents", "consumed_share", "elapsed_share", "over_burn",
          "at_risk", "risk_reasons")


def _summary(project: dict) -> dict:
    """Budget figures for one project."""
    data = {k: project[k] for k in FIELDS}
    data["remaining_cents"] = project["budget_cents"] - project["consumed_cents"]
    data["unplanned_cents"] = project["budget_cents"] - project["planned_cents"]
    return data


@router.get("/")
def list_budgets(request: Request, cur) -> dict:
    """Budget vs planned vs consumed for every visible project."""
    user, q = request.user, request.query
    filters = Filters()
    visible = visible_project_ids(user)
    if visible is not None:
        sql, params = visible
        filters.add(f"id IN ({sql})", *params)
    archived = choice_param(q, "archived", ("true", "false", "all")) or "false"
    if archived != "all":
        filters.eq("is_archived", archived == "true")
    filters.search(["name", "code", "manager_name"], q.get("q"))
    if choice_param(q, "over_burn", ("true", "false")) == "true":
        filters.add("over_burn")
    result = paginated(cur, PROJECT_SELECT, filters, order_by(q, SORTS, "name"), q)
    result["items"] = [_summary(present_project(p)) for p in result["items"]]
    return response(200, result)


@router.get("/{id}")
def get_budget(request: Request, cur) -> dict:
    """One project's budget; admins and its manager also get per-person and per-week breakdowns."""
    user = request.user
    project = present_project(load_visible_project(cur, user, request.params["id"]))
    result = _summary(project)
    if can_manage_project(user, project):
        cur.execute(
            f"""SELECT u.id AS user_id, u.first_name || ' ' || u.last_name AS full_name, u.job_title,
                       SUM({PLANNED_COST_SQL})::bigint AS planned_cents,
                       SUM(a.hours_per_week * ((a.end_date - a.start_date + 1) / 7.0))::numeric(10,1) AS planned_hours
                FROM project_assignments a JOIN users u ON u.id = a.user_id
                WHERE a.project_id = %s AND NOT a.is_archived
                GROUP BY u.id ORDER BY full_name""",  # nosec B608 - constant SQL fragments
            [project["id"]],
        )
        people = {r["user_id"]: {**r, "consumed_cents": 0, "approved_hours": 0} for r in cur.fetchall()}
        cur.execute(
            f"""SELECT u.id AS user_id, u.first_name || ' ' || u.last_name AS full_name, u.job_title,
                       SUM({CONSUMED_COST_SQL})::bigint AS consumed_cents, SUM(t.hours) AS approved_hours
                FROM time_entries t JOIN users u ON u.id = t.user_id
                WHERE t.project_id = %s AND t.status = 'approved'
                GROUP BY u.id""",  # nosec B608
            [project["id"]],
        )
        for row in cur.fetchall():
            person = people.setdefault(row["user_id"], {**row, "planned_cents": 0, "planned_hours": 0})
            person["consumed_cents"] = row["consumed_cents"]
            person["approved_hours"] = row["approved_hours"]
        result["people"] = sorted(people.values(), key=lambda p: p["full_name"])
        cur.execute(
            f"""SELECT date_trunc('month', t.work_date)::date AS month,
                       SUM({CONSUMED_COST_SQL})::bigint AS consumed_cents, SUM(t.hours) AS hours
                FROM time_entries t JOIN users u ON u.id = t.user_id
                WHERE t.project_id = %s AND t.status = 'approved'
                GROUP BY 1 ORDER BY 1""",  # nosec B608
            [project["id"]],
        )
        result["by_month"] = cur.fetchall()
    return response(200, result)


@router.put("/{id}")
def set_budget(request: Request, cur) -> dict:
    """Set a project's budget (admin, or the project's manager)."""
    user = request.user
    project = load_managed_project(cur, user, request.params["id"])
    data = validate(request.body, BUDGET_SCHEMA)
    if data["budget_cents"] is None:
        raise bad_request("Validation failed", {"budget_cents": "is required"})
    if data["budget_cents"] != project["budget_cents"]:
        cur.execute("UPDATE projects SET budget_cents = %s, updated_at = now() WHERE id = %s",
                    [data["budget_cents"], project["id"]])
        audit.record(cur, user, "project", project["id"], "update",
                     f"set the budget of {project['code']} {project['name']} to "
                     f"${data['budget_cents'] / 100:,.2f}",
                     {"budget_cents": {"from": project["budget_cents"], "to": data["budget_cents"]}})
    return response(200, _summary(present_project(get_project(cur, project["id"]))))


handler = make_handler(router, "budgets")
