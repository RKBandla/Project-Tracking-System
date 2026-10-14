"""
Auth VIEW: the JSON shapes the auth service sends back.

Password hashes are never sent.
"""

from shared.auth import issue_tokens
from shared.http import response
from shared.users import serialize_user


def session(user: dict) -> dict:
    """Response with a new token pair plus the user's profile."""
    return response(200, {**issue_tokens(user), "user": serialize_user(user, user)})


def me(user: dict) -> dict:
    """Response with the signed-in user's own profile."""
    return response(200, serialize_user(user, user))
