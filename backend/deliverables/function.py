"""
Deliverables service: work items on a project, with "depends on" links.

Routes (relative to /api/deliverables):
    GET  /                  list deliverables on visible projects (search, filters, sort)
    GET  /graph             dependency graph for one project (?project_id=)
    POST /                  create deliverable (admin, or the project's manager)
    GET  /{id}              view deliverable
    PUT  /{id}              update deliverable, including ``depends_on`` (list of ids)
    POST /{id}/archive      archive (nothing is deleted)
    POST /{id}/reactivate   restore an archived deliverable

Rules:
- dependencies must be on the same project and can't form a loop;
- a deliverable can't be marked done while something it depends on isn't done;
- a milestone (``is_milestone``) is a checkpoint with a single date: it needs a
  due date and has no separate start date.
"""

from shared import audit
from shared.app import make_handler
from shared.errors import bad_request, conflict, not_found
from shared.http import Request, Router, response
from shared.query import Filters, choice_param, date_param, int_param, order_by, paginated
from shared.rbac import load_managed_project, load_visible_project, visible_project_ids
from shared.schema import DELIVERABLE_STATUSES
from shared.validation import Field, check_date_range, validate

router = Router()

FIELDS = {
    "title": Field(required=True, max_length=200),
    "description": Field(kind="text", max_length=5000),
    "status": Field(choices=DELIVERABLE_STATUSES),
    "start_date": Field(kind="date", nullable=True),
    "due_date": Field(kind="date", nullable=True),
    "assignee_id": Field(kind="int", nullable=True, min_value=1),
    "progress_pct": Field(kind="int", min_value=0, max_value=100),
    "is_milestone": Field(kind="bool"),
}
CREATE_SCHEMA = {"project_id": Field(kind="int", required=True, min_value=1), **FIELDS}

SELECT = """
    SELECT d.*, p.code AS project_code, p.name AS project_name, p.is_archived AS project_is_archived,
           CASE WHEN u.id IS NULL THEN NULL ELSE u.first_name || ' ' || u.last_name END AS assignee_name,
           (NOT d.is_archived AND d.status <> 'done' AND d.due_date < CURRENT_DATE) AS is_overdue,
           COALESCE((SELECT array_agg(dd.depends_on_id ORDER BY dd.depends_on_id)
                       FROM deliverable_dependencies dd
                      WHERE dd.deliverable_id = d.id AND dd.archived_at IS NULL), '{}') AS depends_on,
           EXISTS (SELECT 1 FROM deliverable_dependencies dd JOIN deliverables x ON x.id = dd.depends_on_id
                    WHERE dd.deliverable_id = d.id AND dd.archived_at IS NULL
                      AND NOT x.is_archived AND x.status <> 'done') AS is_blocked
    FROM deliverables d
    JOIN projects p ON p.id = d.project_id
    LEFT JOIN users u ON u.id = d.assignee_id
"""
SORTS = {"due_date": "due_date", "start_date": "start_date", "title": "title", "status": "status",
         "progress_pct": "progress_pct", "created_at": "created_at", "updated_at": "updated_at",
         "project_name": "project_name"}


def _scope(user: dict, filters: Filters) -> Filters:
    """Restrict to deliverables on projects the user may view."""
    visible = visible_project_ids(user)
    if visible is not None:
        sql, params = visible
        filters.add(f"project_id IN ({sql})", *params)
    return filters


def _load(cur, user: dict, deliverable_id: int) -> dict:
    """Fetch a visible deliverable or raise 404."""
    filters = _scope(user, Filters()).eq("id", deliverable_id)
    cur.execute(f"SELECT * FROM ({SELECT}) AS t {filters.where()}", filters.params)  # nosec B608
    row = cur.fetchone()
    if row is None:
        raise not_found("Deliverable")
    return row


def _check_assignee(cur, project: dict, assignee_id: int | None) -> None:
    """An assignee must be booked on the project or be its manager."""
    if assignee_id is None or assignee_id == project["manager_id"]:
        return
    cur.execute("SELECT 1 FROM project_assignments WHERE project_id = %s AND user_id = %s AND NOT is_archived",
                [project["id"], assignee_id])
    if not cur.fetchone():
        raise bad_request("Validation failed", {"assignee_id": "must be assigned to the project"})


def _parse_depends_on(body: dict) -> list[int] | None:
    """Pop and validate the ``depends_on`` list from a request body."""
    if "depends_on" not in body:
        return None
    value = body.pop("depends_on")
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, int) and not isinstance(v, bool) and v > 0
                                              for v in value):
        raise bad_request("Validation failed", {"depends_on": "must be a list of deliverable ids"})
    return sorted(set(value))


def _check_dependencies(cur, project_id: int, deliverable_id: int | None, depends_on: list[int]) -> None:
    """Dependencies must be active deliverables on the same project and must not form a loop."""
    if not depends_on:
        return
    if deliverable_id in depends_on:
        raise bad_request("Validation failed", {"depends_on": "a deliverable cannot depend on itself"})
    cur.execute("SELECT id FROM deliverables WHERE id = ANY(%s::int[]) AND project_id = %s AND NOT is_archived",
                [depends_on, project_id])
    found = {r["id"] for r in cur.fetchall()}
    missing = [d for d in depends_on if d not in found]
    if missing:
        raise bad_request("Validation failed",
                          {"depends_on": f"not active deliverables on this project: {missing}"})
    if deliverable_id is None:
        return
    # A loop exists if this deliverable is reachable from any new dependency
    cur.execute(
        """
        WITH RECURSIVE reach(id, path) AS (
            SELECT d, ARRAY[d] FROM unnest(%s::int[]) AS d
            UNION ALL
            SELECT dd.depends_on_id, r.path || dd.depends_on_id
            FROM deliverable_dependencies dd JOIN reach r ON dd.deliverable_id = r.id
            WHERE dd.archived_at IS NULL AND NOT dd.depends_on_id = ANY(r.path)
        )
        SELECT path FROM reach WHERE id = %s LIMIT 1
        """,
        [depends_on, deliverable_id],
    )
    loop = cur.fetchone()
    if loop:
        cycle = [deliverable_id, *loop["path"]]
        cur.execute("SELECT id, title FROM deliverables WHERE id = ANY(%s::int[])", [cycle])
        titles = {r["id"]: r["title"] for r in cur.fetchall()}
        raise conflict(
            "That dependency would create a loop: " + " → ".join(titles.get(i, str(i)) for i in cycle),
            {"cycle": cycle},
        )


def _set_dependencies(cur, user_id: int, deliverable_id: int, depends_on: list[int]) -> None:
    """Replace a deliverable's active dependency links (removed links are archived)."""
    cur.execute(
        "UPDATE deliverable_dependencies SET archived_at = now() "
        "WHERE deliverable_id = %s AND archived_at IS NULL AND NOT depends_on_id = ANY(%s::int[])",
        [deliverable_id, depends_on],
    )
    for depends_on_id in depends_on:
        cur.execute(
            """INSERT INTO deliverable_dependencies (deliverable_id, depends_on_id, created_by)
               SELECT %s, %s, %s WHERE NOT EXISTS (
                   SELECT 1 FROM deliverable_dependencies
                   WHERE deliverable_id = %s AND depends_on_id = %s AND archived_at IS NULL)""",
            [deliverable_id, depends_on_id, user_id, deliverable_id, depends_on_id],
        )


def _check_can_finish(cur, deliverable_id: int) -> None:
    """Refuse 'done' while any active dependency is not done."""
    cur.execute(
        """SELECT x.id, x.title, x.status FROM deliverable_dependencies dd
           JOIN deliverables x ON x.id = dd.depends_on_id
           WHERE dd.deliverable_id = %s AND dd.archived_at IS NULL AND NOT x.is_archived AND x.status <> 'done'
           ORDER BY x.id""",
        [deliverable_id],
    )
    open_deps = cur.fetchall()
    if open_deps:
        raise conflict(
            "Can't mark this done while it depends on unfinished work: "
            + ", ".join(f"{d['title']} ({d['status'].replace('_', ' ')})" for d in open_deps),
            {"open_dependencies": open_deps},
        )


def _normalise(data: dict) -> dict:
    """Apply defaults: done means 100% progress; empty text becomes ''."""
    if data.get("status") == "done" and "progress_pct" not in data:
        data["progress_pct"] = 100
    if "description" in data and data["description"] is None:
        data["description"] = ""
    if "is_milestone" in data and data["is_milestone"] is None:
        data["is_milestone"] = False
    for required in ("status", "progress_pct"):
        if required in data and data[required] is None:
            raise bad_request("Validation failed", {required: "is required"})
    return data


def _check_milestone(is_milestone: bool, start_date, due_date) -> None:
    """A milestone is a single date: it needs a due date and no different start date."""
    if not is_milestone:
        return
    if due_date is None:
        raise bad_request("Validation failed", {"due_date": "a milestone needs a date"})
    if start_date is not None and start_date != due_date:
        raise bad_request("Validation failed",
                          {"start_date": "a milestone has a single date; leave the start date empty"})


@router.get("/")
def list_deliverables(request: Request, cur) -> dict:
    """List deliverables."""
    user, q = request.user, request.query
    filters = _scope(user, Filters())
    filters.eq("project_id", int_param(q, "project_id"))
    filters.eq("assignee_id", int_param(q, "assignee_id"))
    filters.eq("status", choice_param(q, "status", DELIVERABLE_STATUSES))
    filters.search(["title", "description", "project_name", "assignee_name"], q.get("q"))
    if choice_param(q, "overdue", ("true", "false")) == "true":
        filters.add("is_overdue")
    if choice_param(q, "blocked", ("true", "false")) == "true":
        filters.add("is_blocked")
    milestone = choice_param(q, "milestone", ("true", "false"))
    if milestone:
        filters.eq("is_milestone", milestone == "true")
    due_after = date_param(q, "due_after")
    if due_after:
        filters.add("due_date >= %s", due_after)
    due_before = date_param(q, "due_before")
    if due_before:
        filters.add("due_date <= %s", due_before)
    archived = choice_param(q, "archived", ("true", "false", "all")) or "false"
    if archived != "all":
        filters.eq("is_archived", archived == "true")
    return response(200, paginated(cur, SELECT, filters, order_by(q, SORTS, "due_date"), q))


@router.get("/graph")
def graph(request: Request, cur) -> dict:
    """Dependency graph for one project: nodes in dependency order (levels) and edges."""
    user = request.user
    project_id = int_param(request.query, "project_id")
    if project_id is None:
        raise bad_request("Validation failed", {"project_id": "is required"})
    load_visible_project(cur, user, project_id)
    cur.execute(f"SELECT * FROM ({SELECT}) AS t WHERE project_id = %s AND NOT is_archived "  # nosec B608
                "ORDER BY due_date NULLS LAST, id", [project_id])
    nodes = cur.fetchall()
    ids = {n["id"] for n in nodes}
    edges = [{"from": dep, "to": n["id"]} for n in nodes for dep in n["depends_on"] if dep in ids]

    # Longest-path level: a deliverable sits one level after its deepest dependency
    level: dict[int, int] = {}

    def depth(node_id: int, seen: frozenset = frozenset()) -> int:
        if node_id in level:
            return level[node_id]
        deps = [d for d in by_id[node_id]["depends_on"] if d in ids and d not in seen]
        value = 0 if not deps else 1 + max(depth(d, seen | {node_id}) for d in deps)
        level[node_id] = value
        return value

    by_id = {n["id"]: n for n in nodes}
    for n in nodes:
        n["level"] = depth(n["id"])
    return response(200, {"project_id": project_id, "nodes": nodes, "edges": edges})


@router.post("/")
def create_deliverable(request: Request, cur) -> dict:
    """Create a deliverable on a managed project."""
    user = request.user
    body = dict(request.body)
    depends_on = _parse_depends_on(body) or []
    data = validate(body, CREATE_SCHEMA)
    project = load_managed_project(cur, user, data["project_id"])
    check_date_range(data["start_date"], data["due_date"], "start_date", "due_date")
    data = _normalise({k: v for k, v in data.items()
                       if v is not None or k in ("due_date", "start_date", "assignee_id")})
    is_milestone = data.get("is_milestone", False)
    _check_milestone(is_milestone, data.get("start_date"), data.get("due_date"))
    _check_assignee(cur, project, data.get("assignee_id"))
    _check_dependencies(cur, project["id"], None, depends_on)
    cur.execute(
        """
        INSERT INTO deliverables (project_id, title, description, status, start_date, due_date, assignee_id,
                                  progress_pct, is_milestone, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        [project["id"], data["title"], data.get("description", ""), data.get("status", "todo"),
         data.get("start_date"), data.get("due_date"), data.get("assignee_id"), data.get("progress_pct", 0),
         is_milestone, user["id"]],
    )
    deliverable_id = cur.fetchone()["id"]
    _set_dependencies(cur, user["id"], deliverable_id, depends_on)
    if data.get("status") == "done":
        _check_can_finish(cur, deliverable_id)
    audit.record(cur, user, "deliverable", deliverable_id, "create",
                 f"added {'milestone' if is_milestone else 'deliverable'} \"{data['title']}\" to {project['code']}",
                 {**data, "depends_on": depends_on})
    return response(201, _load(cur, user, deliverable_id))


@router.get("/{id}")
def get_one(request: Request, cur) -> dict:
    """View a deliverable."""
    return response(200, _load(cur, request.user, request.params["id"]))


@router.put("/{id}")
def update_deliverable(request: Request, cur) -> dict:
    """Update a deliverable on a managed project."""
    user = request.user
    row = _load(cur, user, request.params["id"])
    project = load_managed_project(cur, user, row["project_id"])
    if row["is_archived"]:
        raise conflict("Deliverable is archived; reactivate it first")
    body = dict(request.body)
    depends_on = _parse_depends_on(body)
    data = validate(body, FIELDS, partial=True)
    if not data and depends_on is None:
        raise bad_request("Nothing to update")
    if "title" in data and data["title"] is None:
        raise bad_request("Validation failed", {"title": "is required"})
    data = _normalise(data)
    check_date_range(data.get("start_date", row["start_date"]), data.get("due_date", row["due_date"]),
                     "start_date", "due_date")
    _check_milestone(data.get("is_milestone", row["is_milestone"]), data.get("start_date", row["start_date"]),
                     data.get("due_date", row["due_date"]))
    if "assignee_id" in data and data["assignee_id"] != row["assignee_id"]:
        _check_assignee(cur, project, data["assignee_id"])
    if depends_on is not None:
        _check_dependencies(cur, project["id"], row["id"], depends_on)
        _set_dependencies(cur, user["id"], row["id"], depends_on)
    if data.get("status", row["status"]) == "done" and (data.get("status") == "done" or depends_on is not None):
        _check_can_finish(cur, row["id"])
    changes = audit.diff(row, data)
    if depends_on is not None and depends_on != list(row["depends_on"]):
        changes["depends_on"] = {"from": list(row["depends_on"]), "to": depends_on}
    if data:
        assignments = ", ".join(f"{name} = %s" for name in data)
        cur.execute(f"UPDATE deliverables SET {assignments}, updated_at = now() WHERE id = %s",  # nosec B608
                    [*data.values(), row["id"]])
    if changes:
        audit.record(cur, user, "deliverable", row["id"], "update",
                     f"updated deliverable \"{row['title']}\" on {row['project_code']} ({', '.join(sorted(changes))})",
                     changes)
    return response(200, _load(cur, user, row["id"]))


@router.post("/{id}/archive")
def archive(request: Request, cur) -> dict:
    """Archive a deliverable (kept for history; it no longer blocks dependents)."""
    user = request.user
    row = _load(cur, user, request.params["id"])
    load_managed_project(cur, user, row["project_id"])
    if row["is_archived"]:
        raise conflict("Deliverable is already archived")
    cur.execute("UPDATE deliverables SET is_archived = TRUE, archived_at = now(), updated_at = now() WHERE id = %s",
                [row["id"]])
    audit.record(cur, user, "deliverable", row["id"], "archive",
                 f"archived deliverable \"{row['title']}\" on {row['project_code']}")
    return response(200, _load(cur, user, row["id"]))


@router.post("/{id}/reactivate")
def reactivate(request: Request, cur) -> dict:
    """Restore an archived deliverable."""
    user = request.user
    row = _load(cur, user, request.params["id"])
    load_managed_project(cur, user, row["project_id"])
    if not row["is_archived"]:
        raise conflict("Deliverable is not archived")
    cur.execute("UPDATE deliverables SET is_archived = FALSE, archived_at = NULL, updated_at = now() WHERE id = %s",
                [row["id"]])
    audit.record(cur, user, "deliverable", row["id"], "update",
                 f"restored deliverable \"{row['title']}\" on {row['project_code']}")
    return response(200, _load(cur, user, row["id"]))


handler = make_handler(router, "deliverables")
