"""
API error types translated into consistent JSON error responses.

Every error body has the shape ``{"error": {"code", "message", "details"}}``.
"""

from typing import Any


class ApiError(Exception):
    """An error that maps directly to an HTTP response."""

    def __init__(self, status: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details

    def to_body(self) -> dict:
        """Return the JSON-serialisable error body."""
        body = {"code": self.code, "message": self.message}
        if self.details is not None:
            body["details"] = self.details
        return {"error": body}


def bad_request(message: str, details: Any = None) -> ApiError:
    """400: the request is malformed or fails validation."""
    return ApiError(400, "bad_request", message, details)


def unauthorized(message: str = "Authentication required") -> ApiError:
    """401: missing, invalid or expired credentials."""
    return ApiError(401, "unauthorized", message)


def forbidden(message: str = "You do not have permission to perform this action") -> ApiError:
    """403: authenticated but not allowed."""
    return ApiError(403, "forbidden", message)


def not_found(entity: str = "Resource") -> ApiError:
    """404: the resource does not exist or is not visible to the caller."""
    return ApiError(404, "not_found", f"{entity} not found")


def conflict(message: str, details: Any = None) -> ApiError:
    """409: the request conflicts with current state or a business rule."""
    return ApiError(409, "conflict", message, details)
