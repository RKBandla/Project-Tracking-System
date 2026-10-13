"""
Lambda handler factory: parses the event, ensures the schema, authenticates
the caller, runs the matched route in a transaction and maps errors to
consistent JSON responses.
"""

import logging

import psycopg
from psycopg import errors as pg_errors

from . import db, schema
from .auth import bearer_token, decode_token
from .errors import ApiError, bad_request, conflict, unauthorized
from .http import Request, Router, error_response, response
from .users import get_user

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def authenticate(cur, headers: dict) -> dict:
    """Resolve the bearer token to an active user (fresh from the database)."""
    user_id = decode_token(bearer_token(headers), "access")
    user = get_user(cur, user_id)
    if user is None or not user["is_active"]:
        raise unauthorized("Account is inactive or no longer exists")
    return user


def _database_error(exc: psycopg.Error) -> ApiError | None:
    """Translate constraint violations into client errors (None for anything else)."""
    if isinstance(exc, pg_errors.UniqueViolation):
        return conflict("A record with the same unique value already exists")
    if isinstance(exc, pg_errors.ForeignKeyViolation):
        return bad_request("A referenced record does not exist")
    if isinstance(exc, (pg_errors.CheckViolation, pg_errors.DataError, pg_errors.NotNullViolation)):
        return bad_request("The data violates a database constraint")
    return None


def make_handler(router: Router, service: str):
    """Create the Lambda entry point for a service."""

    def handler(event=None, context=None):  # pylint: disable=unused-argument
        try:
            request = Request.from_event(event, service)
            if request.method == "OPTIONS":
                return response(204)
            route = router.match(request)
            # Schema setup runs in its own transaction so a failing request cannot roll it back
            with db.cursor() as cur:
                schema.ensure_schema(cur)
            with db.cursor() as cur:
                if not route.public:
                    request.user = authenticate(cur, request.headers)
                return route.handler(request, cur)
        except ApiError as err:
            return error_response(err)
        except psycopg.Error as exc:
            mapped = _database_error(exc)
            if mapped is not None:
                return error_response(mapped)
            logger.exception("Database error in %s", service)
            return error_response(ApiError(500, "server_error", "A database error occurred"))
        except Exception:  # pylint: disable=broad-except
            logger.exception("Unhandled error in %s", service)
            return error_response(ApiError(500, "server_error", "An unexpected error occurred"))

    return handler
