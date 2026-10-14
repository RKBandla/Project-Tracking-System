"""
Test harness: runs service handlers in-process against a local PostgreSQL
test database (``pts_test``), which is created on first use and emptied
before every test.

Requires the local PostgreSQL from bin/setup-environment.sh (postgres/postgres123).
"""

import importlib
import importlib.util
import json
import os
from datetime import date, timedelta
import sys
from pathlib import Path

import psycopg
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
TODAY = date.today()
TEST_DB = os.getenv("PTS_TEST_DB", "pts_test")
ADMIN_EMAIL = "admin@pts.test"
ADMIN_PASSWORD = "Adm1n1"

os.environ.update({
    "IS_LOCAL": "true",
    "POSTGRES_HOST": os.getenv("POSTGRES_HOST", "localhost"),
    "POSTGRES_PORT": os.getenv("POSTGRES_PORT", "5432"),
    "POSTGRES_USER": os.getenv("POSTGRES_USER", "postgres"),
    "POSTGRES_PASS": os.getenv("POSTGRES_PASS", "postgres123"),
    "POSTGRES_NAME": TEST_DB,
    "JWT_SECRET": "test-secret-for-unit-tests-only-0123456789",
    "ADMIN_EMAIL": ADMIN_EMAIL,
    "ADMIN_EMPLOYEE_ID": "ADMIN001",
    "ADMIN_PASSWORD": ADMIN_PASSWORD,
})

# Services import the synced "shared" package; in tests it is backend/_shared itself
sys.path.insert(0, str(BACKEND_DIR))
shared = importlib.import_module("_shared")
sys.modules["shared"] = shared

from shared import auth, db, schema  # noqa: E402  pylint: disable=wrong-import-position

# Hash quickly in tests; production uses the full iteration count
auth.PBKDF2_ITERATIONS = 1_000
_original_hash = auth.hash_password
auth.hash_password = lambda password, iterations=1_000: _original_hash(password, iterations)
schema.hash_password = auth.hash_password

SERVICES = ("auth", "users", "projects", "project-requests", "assignments", "deliverables", "budgets",
            "timesheets", "activity")
TABLES = ("notifications", "audit_log", "time_entries", "deliverable_dependencies", "deliverables",
          "project_assignments", "project_requests", "projects", "users")


def _load_service(name: str):
    """Import backend/<name>/function.py under a unique module name."""
    module_name = "svc_" + name.replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, BACKEND_DIR / name / "function.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HANDLERS = {name: _load_service(name).handler for name in SERVICES}


def _ensure_database() -> None:
    """Create the test database if it does not exist."""
    params = {k: os.environ[v] for k, v in (("host", "POSTGRES_HOST"), ("port", "POSTGRES_PORT"),
                                            ("user", "POSTGRES_USER"), ("password", "POSTGRES_PASS"))}
    with psycopg.connect(dbname="postgres", autocommit=True, **params) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", [TEST_DB]).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{TEST_DB}"')


@pytest.fixture(scope="session", autouse=True)
def database():
    """Create the database and schema once per test session."""
    _ensure_database()
    schema.reset_schema_flag()
    with db.cursor() as cur:
        schema.ensure_schema(cur)
    yield
    db.reset()


@pytest.fixture(autouse=True)
def clean_tables(database):  # pylint: disable=unused-argument,redefined-outer-name
    """Empty all tables and restart sequences, then re-seed the admin."""
    with db.cursor() as cur:
        cur.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
        cur.execute("ALTER SEQUENCE employee_number_seq RESTART WITH 1")
        cur.execute("ALTER SEQUENCE project_number_seq RESTART WITH 1")
    schema.reset_schema_flag()
    yield


class Response:
    """A decoded handler response."""

    def __init__(self, raw: dict):
        self.status = raw["statusCode"]
        self.json = json.loads(raw["body"]) if raw.get("body") else None

    def __repr__(self) -> str:
        return f"<Response {self.status} {self.json}>"


class Api:
    """Calls service handlers with Function URL style events."""

    def call(self, service: str, method: str, path: str = "/", body=None, token: str | None = None,
             query: dict | None = None, raw_body: str | None = None) -> Response:
        """Invoke a service handler."""
        headers = {"content-type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        event = {
            "rawPath": f"/api/{service}{'' if path == '/' else path}",
            "requestContext": {"http": {"method": method}},
            "headers": headers,
            "queryStringParameters": {k: str(v) for k, v in (query or {}).items()} or None,
            "body": raw_body if raw_body is not None else (json.dumps(body) if body is not None else None),
        }
        return Response(HANDLERS[service](event, None))

    def login(self, email: str, password: str) -> str:
        """Log in and return an access token."""
        res = self.call("auth", "POST", "/login", {"email": email, "password": password})
        assert res.status == 200, res
        return res.json["access_token"]


@pytest.fixture
def api() -> Api:
    """API client fixture."""
    return Api()


@pytest.fixture
def admin(api):  # pylint: disable=redefined-outer-name
    """The seeded admin: dict with token and id."""
    token = api.login(ADMIN_EMAIL, ADMIN_PASSWORD)
    me = api.call("auth", "GET", "/me", token=token).json
    return {**me, "token": token, "password": ADMIN_PASSWORD}


@pytest.fixture
def make_user(api, admin):  # pylint: disable=redefined-outer-name
    """Factory creating a user through the API and logging them in."""
    counter = {"n": 0}

    def factory(role: str = "employee", manager_id: int | None = None, **extra) -> dict:
        counter["n"] += 1
        n = counter["n"]
        first, last = extra.pop("first_name", f"First{n}"), extra.pop("last_name", f"Last{n}")
        default_email = f"{first}.{last}@example.com".lower().replace(" ", "")  # emails follow the name
        body = {
            "first_name": first,
            "last_name": last,
            "email": extra.pop("email", default_email),
            "job_title": extra.pop("job_title", "Engineer"),
            "salary_cents": extra.pop("salary_cents", 10_400_000),  # $104,000 -> $50/h
            "role": role,
            "manager_id": manager_id,
            **extra,
        }
        res = api.call("users", "POST", "/", body, token=admin["token"])
        assert res.status == 201, res
        token = api.login(res.json["user"]["email"], res.json["temporary_password"])
        return {**res.json["user"], "token": token, "password": res.json["temporary_password"]}

    return factory


@pytest.fixture
def project_factory(api, admin):  # pylint: disable=redefined-outer-name
    """Factory creating a project as admin."""

    def factory(manager_id: int | None = None, **fields) -> dict:
        body = {"name": fields.pop("name", "Apollo"), "manager_id": manager_id,
                "start_date": fields.pop("start_date", str(TODAY - timedelta(days=28))),
                "end_date": fields.pop("end_date", str(TODAY + timedelta(days=84))), **fields}
        res = api.call("projects", "POST", "/", body, token=admin["token"])
        assert res.status == 201, res
        return res.json

    return factory


def monday(offset_weeks: int = 0) -> date:
    """Monday of the current week, shifted by whole weeks."""
    return TODAY - timedelta(days=TODAY.weekday()) + timedelta(weeks=offset_weeks)


@pytest.fixture
def assign(api):  # pylint: disable=redefined-outer-name
    """Book a person onto a project (defaults: this week through 4 weeks later)."""

    def factory(token: str, project: dict, person: dict, hours: int, start: date | None = None,
                end: date | None = None, **extra) -> "Response":
        start = start or monday()
        end = end or (start + timedelta(weeks=4, days=-1))
        return api.call("assignments", "POST", "/", {
            "project_id": project["id"], "user_id": person["id"], "hours_per_week": hours,
            "start_date": str(start), "end_date": str(end), **extra,
        }, token=token)

    return factory
