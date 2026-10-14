"""
Auth CONTROLLER: the routes for signing in.

Each route reads the request, checks the credentials or token, calls the model
(auth_model) for data and returns a view (auth_view).
"""

import auth_model as model
import auth_view as view
from shared.auth import decode_token, verify_password
from shared.errors import bad_request, unauthorized
from shared.http import Request, Router
from shared.validation import Field, validate

router = Router()

LOGIN_SCHEMA = {
    "login": Field(max_length=255),  # username ("First Last") or email
    "email": Field(kind="email"),  # older clients and scripts
    "password": Field(required=True, max_length=128),
}
REFRESH_SCHEMA = {"refresh_token": Field(required=True, max_length=2048)}


def _find_user(cur, identifier: str, password: str) -> dict | None:
    """The user whose email or full name is ``identifier`` and whose password matches."""
    if "@" in identifier:
        user = model.get_user_by_email(cur, identifier)
        candidates = [user] if user else []
    else:
        candidates = model.get_users_by_name(cur, identifier)
    matches = [u for u in candidates if verify_password(password, u["password_hash"])]
    if len(matches) > 1:
        raise unauthorized("More than one person has that name; sign in with your email instead")
    return matches[0] if matches else None


@router.post("/login", public=True)
def login(request: Request, cur) -> dict:
    """Authenticate with a username (first and last name) or email, and a password."""
    data = validate(request.body, LOGIN_SCHEMA)
    identifier = data["login"] or data["email"]
    if not identifier:
        raise bad_request("Validation failed", {"login": "is required"})
    user = _find_user(cur, identifier, data["password"])
    if user is None:
        raise unauthorized("Invalid username, email or password")
    if not user["is_active"]:
        raise unauthorized("Account is inactive; contact an administrator")
    return view.session(user)


@router.post("/refresh", public=True)
def refresh(request: Request, cur) -> dict:
    """Exchange a refresh token for a new token pair."""
    data = validate(request.body, REFRESH_SCHEMA)
    user = model.get_user(cur, decode_token(data["refresh_token"], "refresh"))
    if user is None or not user["is_active"]:
        raise unauthorized("Account is inactive or no longer exists")
    return view.session(user)


@router.get("/me")
def me(request: Request, cur) -> dict:  # pylint: disable=unused-argument
    """Return the authenticated user."""
    return view.me(request.user)
