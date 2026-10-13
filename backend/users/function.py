"""
Users service: accounts, profiles and workload.

Routes (relative to /api/users):
    GET  /                       people directory (admin, manager)
    POST /                       create user (admin) -> generated employee ID + 6-char password
    GET  /me                     own profile
    PUT  /me                     update own first name, last name and email only
    GET  /{id}                   view user (admin, manager, or self)
    PUT  /{id}                   update user (admin; nobody changes their own role or salary)
    POST /{id}/reset-password    generate a new 6-char password (admin)
    GET  /{id}/workload          booked hours per week and assignments

Users are never deleted; admins deactivate them with ``is_active: false``.
Salaries are whole cents and visible to admins, the person's manager and the person.
"""

from datetime import date, timedelta

from shared import audit
from shared.app import make_handler
from shared.auth import generate_password, hash_password
from shared.errors import bad_request, conflict, forbidden, not_found
from shared.http import Request, Router, response
from shared.query import Filters, choice_param, date_param, int_param, order_by, paginated
from shared.rbac import ADMIN, EMPLOYEE, MANAGER, require_role
from shared.rules import MAX_WEEKLY_HOURS, weekly_load
from shared.schema import ROLES
from shared.users import get_user, next_employee_id, serialize_user
from shared.validation import Field, validate

router = Router()

PROFILE_FIELDS = ("first_name", "last_name", "email")

USER_SCHEMA = {
    "first_name": Field(required=True, max_length=100),
    "last_name": Field(required=True, max_length=100),
    "email": Field(kind="email", required=True),
    "job_title": Field(required=True, max_length=150),
    "salary_cents": Field(kind="int", nullable=True, min_value=0, max_value=10**12),
    "role": Field(required=True, choices=ROLES),
    "manager_id": Field(kind="int", nullable=True, min_value=1),
}
UPDATE_SCHEMA = {**USER_SCHEMA, "is_active": Field(kind="bool", required=True)}
PROFILE_SCHEMA = {name: USER_SCHEMA[name] for name in PROFILE_FIELDS}

LIST_SELECT = """
    SELECT u.id, u.employee_id, u.first_name, u.last_name,
           u.first_name || ' ' || u.last_name AS full_name,
           u.email, u.job_title, u.salary_cents, u.role, u.manager_id, u.is_active,
           u.created_at, u.updated_at,
           CASE WHEN m.id IS NULL THEN NULL ELSE m.first_name || ' ' || m.last_name END AS manager_name,
           (SELECT COALESCE(SUM(a.hours_per_week), 0) FROM project_assignments a
              JOIN projects p ON p.id = a.project_id
             WHERE a.user_id = u.id AND NOT a.is_archived AND NOT p.is_archived
               AND CURRENT_DATE BETWEEN a.start_date AND a.end_date)::int AS current_week_hours
    FROM users u
    LEFT JOIN users m ON m.id = u.manager_id
"""
SORTS = {
    "name": "last_name", "first_name": "first_name", "employee_id": "employee_id",
    "email": "email", "role": "role", "job_title": "job_title",
    "current_week_hours": "current_week_hours", "created_at": "created_at",
}


def _load(cur, user_id: int) -> dict:
    """Fetch a user or raise 404."""
    user = get_user(cur, user_id)
    if user is None:
        raise not_found("User")
    return user


def _can_view(viewer: dict, user: dict) -> bool:
    """Admins and managers see the directory; employees only themselves."""
    return viewer["role"] in (ADMIN, MANAGER) or viewer["id"] == user["id"]


def _check_manager(cur, manager_id: int | None, user_id: int | None = None) -> None:
    """Validate a manager reference: active manager/admin, not self, no reporting cycle."""
    if manager_id is None:
        return
    if manager_id == user_id:
        raise bad_request("Validation failed", {"manager_id": "a user cannot manage themselves"})
    manager = get_user(cur, manager_id)
    if manager is None or not manager["is_active"] or manager["role"] not in (ADMIN, MANAGER):
        raise bad_request("Validation failed", {"manager_id": "must be an active manager or admin"})
    if user_id is not None:
        cur.execute(
            """
            WITH RECURSIVE chain AS (
                SELECT id, manager_id FROM users WHERE id = %s
                UNION
                SELECT u.id, u.manager_id FROM users u JOIN chain c ON u.id = c.manager_id
            )
            SELECT 1 FROM chain WHERE id = %s
            """,
            [manager_id, user_id],
        )
        if cur.fetchone():
            raise bad_request("Validation failed", {"manager_id": "would create a reporting cycle"})


@router.get("/")
def list_users(request: Request, cur) -> dict:
    """People directory with search, filters, sorting and pagination."""
    viewer = request.user
    require_role(viewer, ADMIN, MANAGER)
    q = request.query
    filters = Filters()
    filters.search(["full_name", "email", "employee_id", "job_title"], q.get("q"))
    filters.eq("role", choice_param(q, "role", ROLES))
    filters.eq("manager_id", int_param(q, "manager_id"))
    active = choice_param(q, "is_active", ("true", "false"))
    if active is not None:
        filters.eq("is_active", active == "true")
    result = paginated(cur, LIST_SELECT, filters, order_by(q, SORTS, "name"), q)
    result["items"] = [serialize_user(row, viewer) for row in result["items"]]
    return response(200, result)


@router.post("/")
def create_user(request: Request, cur) -> dict:
    """Create a user with a generated employee ID and 6-character password (admin only)."""
    admin = request.user
    require_role(admin, ADMIN)
    data = validate(request.body, USER_SCHEMA)
    _check_manager(cur, data["manager_id"])
    password = generate_password()
    employee_id = next_employee_id(cur)
    cur.execute(
        """
        INSERT INTO users (employee_id, first_name, last_name, email, job_title, salary_cents,
                           role, manager_id, password_hash)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        [employee_id, data["first_name"], data["last_name"], data["email"], data["job_title"],
         data["salary_cents"], data["role"], data["manager_id"], hash_password(password)],
    )
    user_id = cur.fetchone()["id"]
    audit.record(cur, admin, "user", user_id, "create",
                 f"created user {employee_id} {data['first_name']} {data['last_name']} ({data['role']})",
                 {k: v for k, v in data.items() if k != "salary_cents"})
    user = serialize_user(get_user(cur, user_id), admin)
    return response(201, {"user": user, "employee_id": employee_id, "temporary_password": password})


@router.get("/me")
def get_me(request: Request, cur) -> dict:  # pylint: disable=unused-argument
    """Return the caller's own profile."""
    return response(200, serialize_user(request.user, request.user))


@router.put("/me")
def update_me(request: Request, cur) -> dict:
    """Update the caller's own first name, last name and email (nothing else)."""
    body = request.body
    if set(body) - set(PROFILE_FIELDS):
        raise forbidden("You can only update your first name, last name and email")
    data = validate(body, PROFILE_SCHEMA, partial=True)
    if not data:
        raise bad_request("Nothing to update")
    me = request.user
    changes = audit.diff(me, data)
    if changes:
        assignments = ", ".join(f"{name} = %s" for name in data)
        cur.execute(f"UPDATE users SET {assignments}, updated_at = now() WHERE id = %s",  # nosec B608
                    [*data.values(), me["id"]])
        audit.record(cur, me, "user", me["id"], "update", "updated their profile", changes)
    return response(200, serialize_user(get_user(cur, me["id"]), me))


@router.get("/{id}")
def get_one(request: Request, cur) -> dict:
    """View a user."""
    user = _load(cur, request.params["id"])
    if not _can_view(request.user, user):
        raise not_found("User")
    return response(200, serialize_user(user, request.user))


@router.put("/{id}")
def update_user(request: Request, cur) -> dict:
    """Update a user (admin only). Nobody changes their own role or salary."""
    admin = request.user
    require_role(admin, ADMIN)
    user_id = request.params["id"]
    user = get_user(cur, user_id, lock=True)
    if user is None:
        raise not_found("User")
    data = validate(request.body, UPDATE_SCHEMA, partial=True)
    if not data:
        raise bad_request("Nothing to update")

    if user_id == admin["id"]:
        if "role" in data and data["role"] != user["role"]:
            raise forbidden("Nobody can change their own role")
        if "salary_cents" in data and data["salary_cents"] != user["salary_cents"]:
            raise forbidden("Nobody can change their own salary")
        if data.get("is_active") is False:
            raise conflict("You cannot deactivate your own account")
    if "manager_id" in data:
        _check_manager(cur, data["manager_id"], user_id)

    new_role = data.get("role", user["role"])
    leaving_management = user["role"] in (ADMIN, MANAGER) and new_role == EMPLOYEE
    if leaving_management or data.get("is_active") is False:
        cur.execute("SELECT count(*) AS n FROM users WHERE manager_id = %s AND is_active", [user_id])
        reports = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM projects WHERE manager_id = %s AND NOT is_archived", [user_id])
        projects = cur.fetchone()["n"]
        if reports or projects:
            raise conflict(
                "Reassign this user's direct reports and managed projects first",
                {"direct_reports": reports, "managed_projects": projects},
            )

    changes = audit.diff(user, data)
    if changes:
        assignments = ", ".join(f"{name} = %s" for name in data)
        cur.execute(f"UPDATE users SET {assignments}, updated_at = now() WHERE id = %s",  # nosec B608
                    [*data.values(), user_id])
        logged = {k: v for k, v in changes.items() if k != "salary_cents"}
        if "salary_cents" in changes:
            logged["salary_cents"] = "changed"
        action = "archive" if data.get("is_active") is False else "update"
        audit.record(cur, admin, "user", user_id, action,
                     f"{'deactivated' if action == 'archive' else 'updated'} user {user['employee_id']} "
                     f"{user['first_name']} {user['last_name']}", logged)
    return response(200, serialize_user(get_user(cur, user_id), admin))


@router.post("/{id}/reset-password")
def reset_password(request: Request, cur) -> dict:
    """Generate a new 6-character password (admin only)."""
    admin = request.user
    require_role(admin, ADMIN)
    user = _load(cur, request.params["id"])
    password = generate_password()
    cur.execute("UPDATE users SET password_hash = %s, updated_at = now() WHERE id = %s",
                [hash_password(password), user["id"]])
    audit.record(cur, admin, "user", user["id"], "update",
                 f"reset the password of {user['employee_id']} {user['first_name']} {user['last_name']}")
    return response(200, {"employee_id": user["employee_id"], "email": user["email"],
                          "temporary_password": password})


@router.get("/{id}/workload")
def workload(request: Request, cur) -> dict:
    """Booked hours per week for the next weeks, plus active assignments."""
    user = _load(cur, request.params["id"])
    if not _can_view(request.user, user):
        raise not_found("User")
    q = request.query
    start = date_param(q, "from") or date.today()
    weeks = min(int_param(q, "weeks") or 8, 52)
    end = start + timedelta(weeks=weeks)
    cur.execute(
        """
        SELECT a.id, a.project_id, p.code AS project_code, p.name AS project_name,
               a.project_role, a.hours_per_week, a.start_date, a.end_date
        FROM project_assignments a JOIN projects p ON p.id = a.project_id
        WHERE a.user_id = %s AND NOT a.is_archived AND NOT p.is_archived AND a.end_date >= %s
        ORDER BY a.start_date, p.name
        """,
        [user["id"], start],
    )
    assignments = cur.fetchall()
    load = weekly_load(cur, user["id"], start, end)
    this_week = next((w["hours"] for w in load if w["week_start"] <= start < w["week_start"] + timedelta(days=7)), 0)
    return response(200, {
        "user_id": user["id"],
        "max_hours": MAX_WEEKLY_HOURS,
        "current_week_hours": this_week,
        "peak_hours": max((w["hours"] for w in load), default=0),
        "weeks": [{"week_start": w["week_start"], "hours": w["hours"], "projects": w["projects"]} for w in load],
        "assignments": assignments,
    })


handler = make_handler(router, "users")
