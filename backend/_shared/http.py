"""
HTTP helpers for Lambda Function URL events: request parsing, routing and responses.

Requests arrive with either the full CloudFront path (``/api/<service>/5``) or,
through the local proxy, only the remainder (``/5``). Both are normalised so
routes are always declared relative to the service root.
"""

import base64
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable

from .errors import ApiError, bad_request

JSON_HEADERS = {"Content-Type": "application/json"}


def _json_default(value: Any) -> Any:
    """Serialise types psycopg returns that json does not support natively."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Unsupported type: {type(value).__name__}")


def response(status: int, body: Any = None) -> dict:
    """Build a Lambda Function URL response."""
    result = {"statusCode": status, "headers": dict(JSON_HEADERS)}
    if body is not None:
        result["body"] = json.dumps(body, default=_json_default)
    return result


def error_response(err: ApiError) -> dict:
    """Build a response from an ApiError."""
    return response(err.status, err.to_body())


@dataclass
class Request:
    """A parsed Lambda Function URL request."""

    method: str
    path: str
    query: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    raw_body: str = ""
    params: dict[str, int] = field(default_factory=dict)
    user: dict | None = None

    @property
    def body(self) -> dict:
        """The JSON body as a dict (empty dict when there is no body)."""
        if not self.raw_body:
            return {}
        try:
            data = json.loads(self.raw_body)
        except json.JSONDecodeError as exc:
            raise bad_request("Request body must be valid JSON") from exc
        if not isinstance(data, dict):
            raise bad_request("Request body must be a JSON object")
        return data

    @classmethod
    def from_event(cls, event: dict, service: str) -> "Request":
        """Parse a Function URL (payload v2) event."""
        event = event or {}
        http = (event.get("requestContext") or {}).get("http") or {}
        method = (http.get("method") or event.get("httpMethod") or "GET").upper()
        raw_path = event.get("rawPath") or http.get("path") or event.get("path") or "/"
        body = event.get("body") or ""
        if body and event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8")
        headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        return cls(
            method=method,
            path=normalise_path(raw_path, service),
            query=dict(event.get("queryStringParameters") or {}),
            headers=headers,
            raw_body=body,
        )


def normalise_path(raw_path: str, service: str) -> str:
    """Strip an optional ``/api/<service>`` prefix and trailing slashes."""
    path = "/" + raw_path.strip("/")
    prefix = f"/api/{service}"
    if path == prefix or path.startswith(prefix + "/"):
        path = path[len(prefix):] or "/"
    return path if path == "/" else path.rstrip("/")


# Route handlers receive the request and an open database cursor
Handler = Callable[[Request, Any], dict]


@dataclass
class Route:
    """A single route: HTTP method, compiled path pattern and handler."""

    method: str
    pattern: re.Pattern
    handler: Handler
    public: bool


class Router:
    """Minimal router. ``{name}`` path segments match positive integers."""

    def __init__(self) -> None:
        self.routes: list[Route] = []

    def add(self, method: str, path: str, public: bool = False) -> Callable[[Handler], Handler]:
        """Decorator registering a handler for ``method`` and ``path``."""
        regex = "^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[0-9]+)", path.rstrip("/") or "/") + "$"

        def decorator(func: Handler) -> Handler:
            self.routes.append(Route(method.upper(), re.compile(regex), func, public))
            return func

        return decorator

    def get(self, path: str, public: bool = False):
        """Register a GET route."""
        return self.add("GET", path, public)

    def post(self, path: str, public: bool = False):
        """Register a POST route."""
        return self.add("POST", path, public)

    def put(self, path: str, public: bool = False):
        """Register a PUT route."""
        return self.add("PUT", path, public)

    def delete(self, path: str, public: bool = False):
        """Register a DELETE route."""
        return self.add("DELETE", path, public)

    def match(self, request: Request) -> Route:
        """Find the route for a request, setting ``request.params``."""
        path_matched = False
        for route in self.routes:
            found = route.pattern.match(request.path)
            if not found:
                continue
            path_matched = True
            if route.method == request.method:
                request.params = {k: int(v) for k, v in found.groupdict().items()}
                return route
        if path_matched:
            raise ApiError(405, "method_not_allowed", f"Method {request.method} not allowed")
        raise ApiError(404, "not_found", f"No route for {request.method} {request.path}")
