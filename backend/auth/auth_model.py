"""
Auth MODEL: the user lookups needed to sign in.

The auth service has no SQL of its own: finding a user by id, email or full
name lives in shared.users (other services use it too) and is re-exported
here so the controller only talks to its model. Nothing here knows about HTTP.
"""

from shared.users import get_user, get_user_by_email, get_users_by_name  # lookups shared with other services

__all__ = ["get_user", "get_user_by_email", "get_users_by_name"]
