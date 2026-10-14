"""
Users CONTROLLER: the routes for people.

Each route reads the request, checks permissions and rules, calls the model
(users_model) for data and returns a view (users_view).

Emails must be made from the person's name: the full name or the initials
(Eli Engineer -> eli.engineer@, eliengineer@ or ee@). Checked whenever the
name or email is set or changed.
"""

from datetime import date, timedelta

import users_model as model
import users_view as view
from shared import audit
from shared.auth import generate_password, hash_password
from shared.errors import bad_request, conflict, forbidden, not_found
from shared.http import Request, Router
from shared.query import Filters, choice_param, date_param, int_param, order_by
from shared.rbac import ADMIN, EMPLOYEE, MANAGER, require_role
from shared.rules import MAX_WEEKLY_HOURS, weekly_load
from shared.schema import ROLES
from shared.users import email_matches_name, email_rule_hint
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


def _load(cur, user_id: int) -> dict:
    """Fetch a user or raise 404."""
    user = model.get_user(cur, user_id)
    if user is None:
        raise not_found("User")
    return user


def _can_view(viewer: dict, user: dict) -> bool:
    """Admins and managers see the directory; employees only themselves."""
    return viewer["role"] in (ADMIN, MANAGER) or viewer["id"] == user["id"]


def _check_email(current: dict | None, data: dict) -> None:
    """Refuse an email that isn't the full name or initials, when the name or email changes."""
    current = current or {}
    if current and not any(k in data and data[k] != current.get(k) for k in PROFILE_FIELDS):
        return
    merged = {k: data.get(k, current.get(k)) or "" for k in PROFILE_FIELDS}
    if not email_matches_name(merged["email"], merged["first_name"], merged["last_name"]):
        raise bad_request("Validation failed",
                          {"email": email_rule_hint(merged["first_name"], merged["last_name"])})


def _check_manager(cur, manager_id: int | None, user_id: int | None = None) -> None:
    """Validate a manager reference: active manager/admin, not self, no reporting cycle."""
    if manager_id is None:
        return
    if manager_id == user_id:
        raise bad_request("Validation failed", {"manager_id": "a user cannot manage themselves"})
    manager = model.get_user(cur, manager_id)
    if manager is None or not manager["is_active"] or manager["role"] not in (ADMIN, MANAGER):
        raise bad_request("Validation failed", {"manager_id": "must be an active manager or admin"})
    if user_id is not None and model.would_create_reporting_cycle(cur, manager_id, user_id):
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
    return view.user_list(model.list_users(cur, filters, order_by(q, model.SORTS, "name"), q), viewer)


@router.post("/")
def create_user(request: Request, cur) -> dict:
    """Create a user with a generated employee ID and 6-character password (admin only)."""
    admin = request.user
    require_role(admin, ADMIN)
    data = validate(request.body, USER_SCHEMA)
    _check_email(None, data)
    _check_manager(cur, data["manager_id"])
    password = generate_password()
    employee_id = model.next_employee_id(cur)
    user_id = model.insert_user(cur, data, employee_id, hash_password(password))
    audit.record(cur, admin, "user", user_id, "create",
                 f"created user {employee_id} {data['first_name']} {data['last_name']} ({data['role']})",
                 {k: v for k, v in data.items() if k != "salary_cents"})
    return view.created(model.get_user(cur, user_id), admin, employee_id, password)


@router.get("/me")
def get_me(request: Request, cur) -> dict:  # pylint: disable=unused-argument
    """Return the caller's own profile."""
    return view.user(request.user, request.user)


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
    _check_email(me, data)
    changes = audit.diff(me, data)
    if changes:
        model.update_user(cur, me["id"], data)
        audit.record(cur, me, "user", me["id"], "update", "updated their profile", changes)
    return view.user(model.get_user(cur, me["id"]), me)


@router.get("/{id}")
def get_one(request: Request, cur) -> dict:
    """View a user."""
    user = _load(cur, request.params["id"])
    if not _can_view(request.user, user):
        raise not_found("User")
    return view.user(user, request.user)


@router.put("/{id}")
def update_user(request: Request, cur) -> dict:
    """Update a user (admin only). Nobody changes their own role or salary."""
    admin = request.user
    require_role(admin, ADMIN)
    user_id = request.params["id"]
    user = model.get_user(cur, user_id, lock=True)
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
    _check_email(user, data)
    if "manager_id" in data:
        _check_manager(cur, data["manager_id"], user_id)

    new_role = data.get("role", user["role"])
    leaving_management = user["role"] in (ADMIN, MANAGER) and new_role == EMPLOYEE
    if leaving_management or data.get("is_active") is False:
        reports, projects = model.count_reports_and_projects(cur, user_id)
        if reports or projects:
            raise conflict(
                "Reassign this user's direct reports and managed projects first",
                {"direct_reports": reports, "managed_projects": projects},
            )

    changes = audit.diff(user, data)
    if changes:
        model.update_user(cur, user_id, data)
        logged = {k: v for k, v in changes.items() if k != "salary_cents"}
        if "salary_cents" in changes:
            logged["salary_cents"] = "changed"
        action = "archive" if data.get("is_active") is False else "update"
        audit.record(cur, admin, "user", user_id, action,
                     f"{'deactivated' if action == 'archive' else 'updated'} user {user['employee_id']} "
                     f"{user['first_name']} {user['last_name']}", logged)
    return view.user(model.get_user(cur, user_id), admin)


@router.post("/{id}/reset-password")
def reset_password(request: Request, cur) -> dict:
    """Generate a new 6-character password (admin only)."""
    admin = request.user
    require_role(admin, ADMIN)
    user = _load(cur, request.params["id"])
    password = generate_password()
    model.set_password_hash(cur, user["id"], hash_password(password))
    audit.record(cur, admin, "user", user["id"], "update",
                 f"reset the password of {user['employee_id']} {user['first_name']} {user['last_name']}")
    return view.password_reset(user, password)


@router.get("/{id}/workload")
def workload(request: Request, cur) -> dict:
    """Booked hours per week for the next weeks, plus active assignments."""
    user = _load(cur, request.params["id"])
    if not _can_view(request.user, user):
        raise not_found("User")
    q = request.query
    start = date_param(q, "from") or date.today()
    weeks = min(int_param(q, "weeks") or 8, 52)
    load = weekly_load(cur, user["id"], start, start + timedelta(weeks=weeks))
    return view.workload(user["id"], start, MAX_WEEKLY_HOURS, load, model.active_assignments(cur, user["id"], start))
