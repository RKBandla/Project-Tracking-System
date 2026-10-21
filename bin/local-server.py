#!/usr/bin/env python3
"""
Local API server for Windows (no Docker / LocalStack needed).

Runs all nine Lambda handlers in one process behind http://localhost:3001,
using the same routes the frontend calls: /api/<service>/...

Needs: Python 3.10+, `pip install "psycopg[binary]==3.2.3" PyJWT==2.10.1`
and a local PostgreSQL (user postgres / password postgres123 on port 5432).

Usage (from the project root):
    python bin/local-server.py
Then, in another terminal:
    cd frontend && npm run dev        ->  http://localhost:3000
"""

import importlib
import importlib.util
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

PORT = int(os.getenv("PORT", "3001"))
DB_NAME = os.getenv("POSTGRES_NAME", "pts")
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"

# Local settings (any of these can be overridden by setting the variable first)
for key, value in {
    "IS_LOCAL": "true",
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": "postgres",
    "POSTGRES_PASS": "postgres123",
    "POSTGRES_NAME": DB_NAME,
    "JWT_SECRET": "local-development-secret-change-me",
    "ADMIN_EMAIL": "admin@pts.local",
    "ADMIN_EMPLOYEE_ID": "ADMIN001",
    "ADMIN_PASSWORD": "Admin1",
}.items():
    os.environ.setdefault(key, value)

import psycopg  # noqa: E402  (after the environment is set)

# Every service imports a "shared" package; locally that is backend/_shared itself
sys.path.insert(0, str(BACKEND_DIR))
sys.modules["shared"] = importlib.import_module("_shared")

SERVICES = ("auth", "users", "projects", "project-requests", "assignments", "deliverables", "budgets",
            "timesheets", "activity")


def load_service(name: str):
    """Import backend/<name>/function.py under a unique name and return its handler."""
    sys.path.insert(0, str(BACKEND_DIR / name))
    spec = importlib.util.spec_from_file_location("svc_" + name.replace("-", "_"),
                                                  BACKEND_DIR / name / "function.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.handler


def ensure_database() -> None:
    """Create the local database if it does not exist yet."""
    params = {"host": os.environ["POSTGRES_HOST"], "port": os.environ["POSTGRES_PORT"],
              "user": os.environ["POSTGRES_USER"], "password": os.environ["POSTGRES_PASS"]}
    with psycopg.connect(dbname="postgres", autocommit=True, **params) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", [DB_NAME]).fetchone():
            conn.execute(f'CREATE DATABASE "{DB_NAME}"')
            print(f"Created database {DB_NAME}")


HANDLERS = {}

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, PATCH, OPTIONS",
    "Access-Control-Allow-Headers": "*",
}


class Handler(BaseHTTPRequestHandler):
    """Turns each HTTP request into a Lambda Function URL event."""

    def _send(self, status: int, body: str = "", headers: dict | None = None) -> None:
        self.send_response(status)
        for key, value in {**CORS, "Content-Type": "application/json", **(headers or {})}.items():
            self.send_header(key, value)
        data = body.encode("utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _handle(self) -> None:
        if self.command == "OPTIONS":
            self._send(204)
            return
        parts = urlsplit(self.path)
        segments = [s for s in parts.path.split("/") if s]
        if len(segments) < 2 or segments[0] != "api" or segments[1] not in HANDLERS:
            self._send(404, json.dumps({"error": {"code": "not_found", "message": "Unknown API path",
                                                  "details": {"services": list(HANDLERS)}}}))
            return
        length = int(self.headers.get("Content-Length") or 0)
        event = {
            "rawPath": parts.path,
            "requestContext": {"http": {"method": self.command, "path": parts.path}},
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "queryStringParameters": dict(parse_qsl(parts.query)) or None,
            "body": self.rfile.read(length).decode("utf-8") if length else "",
            "isBase64Encoded": False,
        }
        result = HANDLERS[segments[1]](event, None)
        self._send(result.get("statusCode", 200), result.get("body") or "", result.get("headers"))

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _handle

    def log_message(self, fmt, *args):  # shorter console lines
        sys.stdout.write(f"{self.command} {self.path} -> {args[1] if len(args) > 1 else ''}\n")


def main() -> None:
    ensure_database()
    for name in SERVICES:
        HANDLERS[name] = load_service(name)
    print(f"API running on http://localhost:{PORT}/api/<service>  (services: {', '.join(SERVICES)})")
    print(f"Admin login: {os.environ['ADMIN_EMAIL']} / {os.environ['ADMIN_PASSWORD']}")
    # One request at a time: all services share one database connection
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()