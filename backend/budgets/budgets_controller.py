"""
Budgets CONTROLLER: the routes for project budgets.

Each route reads the request, checks permissions and rules, calls the model
(budgets_model) for data and returns a view (budgets_view).
"""

import budgets_model as model
import budgets_view as view
from shared import audit
from shared.errors import bad_request
from shared.http import Request, Router
from shared.projects import present_project
from shared.query import Filters, choice_param, order_by
from shared.rbac import can_manage_project, load_managed_project, load_visible_project, visible_project_ids
from shared.validation import Field, validate

router = Router()

BUDGET_SCHEMA = {"budget_cents": Field(kind="int", required=True, min_value=0, max_value=10**14)}


def _people(cur, project_id: int) -> list[dict]:
    """Planned and consumed cost per person, merged and sorted by name."""
    people = {r["user_id"]: {**r, "consumed_cents": 0, "approved_hours": 0}
              for r in model.planned_by_person(cur, project_id)}
    for row in model.consumed_by_person(cur, project_id):
        person = people.setdefault(row["user_id"], {**row, "planned_cents": 0, "planned_hours": 0})
        person["consumed_cents"] = row["consumed_cents"]
        person["approved_hours"] = row["approved_hours"]
    return sorted(people.values(), key=lambda p: p["full_name"])


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
    return view.budget_list(model.list_projects(cur, filters, order_by(q, model.SORTS, "name"), q))


@router.get("/{id}")
def get_budget(request: Request, cur) -> dict:
    """One project's budget; admins and its manager also get per-person and per-week breakdowns."""
    user = request.user
    project = present_project(load_visible_project(cur, user, request.params["id"]))
    result = view.summary(project)
    if can_manage_project(user, project):
        result["people"] = _people(cur, project["id"])
        result["by_month"] = model.consumed_by_month(cur, project["id"])
    return view.budget(result)


@router.put("/{id}")
def set_budget(request: Request, cur) -> dict:
    """Set a project's budget (admin, or the project's manager)."""
    user = request.user
    project = load_managed_project(cur, user, request.params["id"])
    data = validate(request.body, BUDGET_SCHEMA)
    if data["budget_cents"] is None:
        raise bad_request("Validation failed", {"budget_cents": "is required"})
    if data["budget_cents"] != project["budget_cents"]:
        model.set_budget(cur, project["id"], data["budget_cents"])
        audit.record(cur, user, "project", project["id"], "update",
                     f"set the budget of {project['code']} {project['name']} to "
                     f"${data['budget_cents'] / 100:,.2f}",
                     {"budget_cents": {"from": project["budget_cents"], "to": data["budget_cents"]}})
    return view.budget(view.summary(present_project(model.get_project(cur, project["id"]))))
