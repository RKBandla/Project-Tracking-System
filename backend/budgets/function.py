"""
Budgets service: planned vs actual budget line items per project.

Routes (relative to /api/budgets):
    GET    /        list budget items with totals (admin, managers for their projects)
    POST   /        create budget item
    GET    /{id}    view budget item
    PUT    /{id}    update budget item
    DELETE /{id}    delete budget item

Employees have no access to budget data. Items on archived projects are read-only.
"""

from shared import audit
from shared.app import make_handler
from shared.errors import bad_request, not_found
from shared.http import Request, Router, response
from shared.query import Filters, choice_param, date_param, int_param, order_by, paginated
from shared.rbac import ADMIN, MANAGER, load_managed_project, require_role, visible_project_ids
from shared.schema import BUDGET_CATEGORIES
from shared.validation import Field, validate

router = Router()

FIELDS = {
    "category": Field(required=True, choices=BUDGET_CATEGORIES),
    "description": Field(required=True, max_length=255),
    "planned_amount": Field(kind="decimal", min_value=0, max_value=999_999_999_999),
    "actual_amount": Field(kind="decimal", min_value=0, max_value=999_999_999_999),
    "entry_date": Field(kind="date"),
}
CREATE_SCHEMA = {"project_id": Field(kind="int", required=True, min_value=1), **FIELDS}

SELECT = """
    SELECT b.*, p.code AS project_code, p.name AS project_name, p.is_archived AS project_is_archived
    FROM budget_items b
    JOIN projects p ON p.id = b.project_id
"""
SORTS = {"entry_date": "entry_date", "category": "category", "description": "description",
         "planned_amount": "planned_amount", "actual_amount": "actual_amount", "created_at": "created_at"}


def _scope(user: dict, filters: Filters) -> Filters:
    """Restrict to items on projects the user manages (all for admins)."""
    require_role(user, ADMIN, MANAGER)
    visible = visible_project_ids(user)
    if visible is not None:
        sql, params = visible
        filters.add(f"project_id IN ({sql})", *params)
    return filters


def _load(cur, user: dict, item_id: int) -> dict:
    """Fetch a visible budget item or raise 404."""
    filters = _scope(user, Filters()).eq("id", item_id)
    cur.execute(f"SELECT * FROM ({SELECT}) AS t {filters.where()}", filters.params)  # nosec B608
    row = cur.fetchone()
    if row is None:
        raise not_found("Budget item")
    return row


@router.get("/")
def list_items(request: Request, cur) -> dict:
    """List budget items with planned/actual totals for the current filter."""
    user, q = request.user, request.query
    filters = _scope(user, Filters())
    filters.eq("project_id", int_param(q, "project_id"))
    filters.eq("category", choice_param(q, "category", BUDGET_CATEGORIES))
    filters.search(["description", "project_name", "project_code"], q.get("q"))
    date_from = date_param(q, "date_from")
    if date_from:
        filters.add("entry_date >= %s", date_from)
    date_to = date_param(q, "date_to")
    if date_to:
        filters.add("entry_date <= %s", date_to)
    result = paginated(cur, SELECT, filters, order_by(q, SORTS, "-entry_date"), q)
    cur.execute(
        f"""SELECT COALESCE(SUM(planned_amount), 0) AS planned, COALESCE(SUM(actual_amount), 0) AS actual
            FROM ({SELECT}) AS t {filters.where()}""",  # nosec B608
        filters.params,
    )
    result["totals"] = cur.fetchone()
    return response(200, result)


@router.post("/")
def create_item(request: Request, cur) -> dict:
    """Add a budget item to a managed project."""
    user = request.user
    _scope(user, Filters())
    data = validate(request.body, CREATE_SCHEMA)
    project = load_managed_project(cur, user, data["project_id"])
    cur.execute(
        """
        INSERT INTO budget_items (project_id, category, description, planned_amount, actual_amount,
                                  entry_date, created_by)
        VALUES (%s, %s, %s, %s, %s, COALESCE(%s, CURRENT_DATE), %s) RETURNING id
        """,
        [project["id"], data["category"], data["description"], data["planned_amount"] or 0,
         data["actual_amount"] or 0, data["entry_date"], user["id"]],
    )
    item_id = cur.fetchone()["id"]
    audit.record(cur, user["id"], "budget_item", item_id, "create", data)
    return response(201, _load(cur, user, item_id))


@router.get("/{id}")
def get_one(request: Request, cur) -> dict:
    """View a budget item."""
    return response(200, _load(cur, request.user, request.params["id"]))


@router.put("/{id}")
def update_item(request: Request, cur) -> dict:
    """Update a budget item on a managed project."""
    user = request.user
    row = _load(cur, user, request.params["id"])
    load_managed_project(cur, user, row["project_id"])
    data = validate(request.body, FIELDS, partial=True)
    if not data:
        raise bad_request("Nothing to update")
    missing = {k: "is required" for k, v in data.items() if v is None}
    if missing:
        raise bad_request("Validation failed", missing)
    changes = audit.diff(row, data)
    if changes:
        assignments = ", ".join(f"{name} = %s" for name in data)
        cur.execute(f"UPDATE budget_items SET {assignments}, updated_at = now() WHERE id = %s",  # nosec B608
                    [*data.values(), row["id"]])
        audit.record(cur, user["id"], "budget_item", row["id"], "update", changes)
    return response(200, _load(cur, user, row["id"]))


@router.delete("/{id}")
def delete_item(request: Request, cur) -> dict:
    """Delete a budget item on a managed project."""
    user = request.user
    row = _load(cur, user, request.params["id"])
    load_managed_project(cur, user, row["project_id"])
    cur.execute("DELETE FROM budget_items WHERE id = %s", [row["id"]])
    audit.record(cur, user["id"], "budget_item", row["id"], "delete",
                 {"project_id": row["project_id"], "description": row["description"]})
    return response(204)


handler = make_handler(router, "budgets")
