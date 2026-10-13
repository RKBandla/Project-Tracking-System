"""
Auth service: log in with employee ID and password, refresh tokens, current user.

Routes (relative to /api/auth):
    POST /login     {employee_id, password}  -> tokens + user   (public)
    POST /refresh   {refresh_token}          -> tokens + user   (public)
    GET  /me                                 -> current user
"""

from shared.app import make_handler
from shared.auth import decode_token, issue_tokens, verify_password
from shared.errors import unauthorized
from shared.http import Request, Router, response
from shared.users import get_user, get_user_by_employee_id, serialize_user
from shared.validation import Field, validate

router = Router()

LOGIN_SCHEMA = {
    "employee_id": Field(required=True, max_length=20),
    "password": Field(required=True, max_length=128),
}
REFRESH_SCHEMA = {"refresh_token": Field(required=True, max_length=2048)}


def _session(user: dict) -> dict:
    """Tokens plus the user's profile."""
    return {**issue_tokens(user), "user": serialize_user(user, user)}


@router.post("/login", public=True)
def login(request: Request, cur) -> dict:
    """Authenticate with employee ID and password."""
    data = validate(request.body, LOGIN_SCHEMA)
    user = get_user_by_employee_id(cur, data["employee_id"])
    if user is None or not verify_password(data["password"], user["password_hash"]):
        raise unauthorized("Invalid employee ID or password")
    if not user["is_active"]:
        raise unauthorized("Account is inactive; contact an administrator")
    return response(200, _session(user))


@router.post("/refresh", public=True)
def refresh(request: Request, cur) -> dict:
    """Exchange a refresh token for a new token pair."""
    data = validate(request.body, REFRESH_SCHEMA)
    user = get_user(cur, decode_token(data["refresh_token"], "refresh"))
    if user is None or not user["is_active"]:
        raise unauthorized("Account is inactive or no longer exists")
    return response(200, _session(user))


@router.get("/me")
def me(request: Request, cur) -> dict:  # pylint: disable=unused-argument
    """Return the authenticated user."""
    return response(200, serialize_user(request.user, request.user))


handler = make_handler(router, "auth")
