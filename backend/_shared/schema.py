"""
Database schema (idempotent) and initial admin seed.

There is no separate migration step in the workshop deployment, so every
service ensures the schema once per Lambda container. A transaction-level
advisory lock serialises concurrent cold starts.

Money is stored as whole cents (BIGINT) everywhere. Nothing is ever deleted:
rows are archived (``is_archived``) or change status instead.
"""

import logging
import os

from .auth import hash_password

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 3  # 3: deliverables.is_milestone

ROLES = ("admin", "manager", "employee")
PROJECT_STATUSES = ("planned", "active", "on_hold", "completed")
REQUEST_STATUSES = ("pending", "approved", "rejected", "withdrawn")
DELIVERABLE_STATUSES = ("todo", "in_progress", "blocked", "done")
TIME_ENTRY_STATUSES = ("pending", "approved", "rejected", "withdrawn")

# Tables from schema version 1 (decimal money, hard deletes). They only ever held
# development data, so they are rebuilt rather than migrated.
V1_TABLES = ("audit_log", "budget_items", "deliverables", "project_assignments", "project_requests",
             "projects", "users")

_SCHEMA_LOCK_ID = 727_001
_SCHEMA_READY = False


def _in(values: tuple) -> str:
    """Render a tuple of constants as a SQL IN list for CHECK constraints."""
    return ", ".join(f"'{v}'" for v in values)


DDL = f"""
CREATE TABLE IF NOT EXISTS schema_meta (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS employee_number_seq START 1;
CREATE SEQUENCE IF NOT EXISTS project_number_seq START 1;

CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    employee_id   VARCHAR(20)  NOT NULL UNIQUE,
    first_name    VARCHAR(100) NOT NULL,
    last_name     VARCHAR(100) NOT NULL,
    email         VARCHAR(255) NOT NULL,
    job_title     VARCHAR(150) NOT NULL DEFAULT '',
    salary_cents  BIGINT CHECK (salary_cents IS NULL OR salary_cents >= 0),
    role          VARCHAR(20)  NOT NULL CHECK (role IN ({_in(ROLES)})),
    manager_id    INTEGER REFERENCES users (id),
    password_hash TEXT         NOT NULL,
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CHECK (manager_id IS NULL OR manager_id <> id)
);
CREATE UNIQUE INDEX IF NOT EXISTS users_email_key ON users (lower(email));
CREATE INDEX IF NOT EXISTS users_manager_idx ON users (manager_id);

CREATE TABLE IF NOT EXISTS projects (
    id           SERIAL PRIMARY KEY,
    code         VARCHAR(20)  NOT NULL UNIQUE,
    name         VARCHAR(200) NOT NULL,
    description  TEXT         NOT NULL DEFAULT '',
    status       VARCHAR(20)  NOT NULL DEFAULT 'planned' CHECK (status IN ({_in(PROJECT_STATUSES)})),
    start_date   DATE,
    end_date     DATE,
    manager_id   INTEGER REFERENCES users (id),
    budget_cents BIGINT       NOT NULL DEFAULT 0 CHECK (budget_cents >= 0),
    is_archived  BOOLEAN      NOT NULL DEFAULT FALSE,
    archived_at  TIMESTAMPTZ,
    archived_by  INTEGER REFERENCES users (id),
    created_by   INTEGER REFERENCES users (id),
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date)
);
CREATE INDEX IF NOT EXISTS projects_manager_idx ON projects (manager_id);

CREATE TABLE IF NOT EXISTS project_requests (
    id                    SERIAL PRIMARY KEY,
    requested_by          INTEGER      NOT NULL REFERENCES users (id),
    name                  VARCHAR(200) NOT NULL,
    description           TEXT         NOT NULL DEFAULT '',
    justification         TEXT         NOT NULL DEFAULT '',
    proposed_start_date   DATE,
    proposed_end_date     DATE,
    proposed_budget_cents BIGINT       NOT NULL DEFAULT 0 CHECK (proposed_budget_cents >= 0),
    status                VARCHAR(20)  NOT NULL DEFAULT 'pending' CHECK (status IN ({_in(REQUEST_STATUSES)})),
    reviewed_by           INTEGER REFERENCES users (id),
    reviewed_at           TIMESTAMPTZ,
    review_note           TEXT         NOT NULL DEFAULT '',
    project_id            INTEGER REFERENCES projects (id),
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS project_assignments (
    id             SERIAL PRIMARY KEY,
    project_id     INTEGER      NOT NULL REFERENCES projects (id),
    user_id        INTEGER      NOT NULL REFERENCES users (id),
    project_role   VARCHAR(100) NOT NULL DEFAULT '',
    hours_per_week INTEGER      NOT NULL CHECK (hours_per_week BETWEEN 1 AND 40),
    start_date     DATE         NOT NULL,
    end_date       DATE         NOT NULL,
    is_archived    BOOLEAN      NOT NULL DEFAULT FALSE,
    archived_at    TIMESTAMPTZ,
    assigned_by    INTEGER REFERENCES users (id),
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CHECK (end_date >= start_date)
);
CREATE INDEX IF NOT EXISTS project_assignments_user_idx ON project_assignments (user_id, start_date, end_date);
CREATE INDEX IF NOT EXISTS project_assignments_project_idx ON project_assignments (project_id);

CREATE TABLE IF NOT EXISTS deliverables (
    id           SERIAL PRIMARY KEY,
    project_id   INTEGER      NOT NULL REFERENCES projects (id),
    title        VARCHAR(200) NOT NULL,
    description  TEXT         NOT NULL DEFAULT '',
    status       VARCHAR(20)  NOT NULL DEFAULT 'todo' CHECK (status IN ({_in(DELIVERABLE_STATUSES)})),
    start_date   DATE,
    due_date     DATE,
    assignee_id  INTEGER REFERENCES users (id),
    progress_pct INTEGER      NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
    is_milestone BOOLEAN      NOT NULL DEFAULT FALSE,
    is_archived  BOOLEAN      NOT NULL DEFAULT FALSE,
    archived_at  TIMESTAMPTZ,
    created_by   INTEGER REFERENCES users (id),
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CHECK (due_date IS NULL OR start_date IS NULL OR due_date >= start_date)
);
CREATE INDEX IF NOT EXISTS deliverables_project_idx ON deliverables (project_id, status);
-- Version 3: milestones are deliverables marked with a single date
ALTER TABLE deliverables ADD COLUMN IF NOT EXISTS is_milestone BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS deliverable_dependencies (
    id             SERIAL PRIMARY KEY,
    deliverable_id INTEGER     NOT NULL REFERENCES deliverables (id),
    depends_on_id  INTEGER     NOT NULL REFERENCES deliverables (id),
    created_by     INTEGER REFERENCES users (id),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at    TIMESTAMPTZ,
    CHECK (deliverable_id <> depends_on_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS deliverable_dependencies_active_key
    ON deliverable_dependencies (deliverable_id, depends_on_id) WHERE archived_at IS NULL;

CREATE TABLE IF NOT EXISTS time_entries (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER       NOT NULL REFERENCES users (id),
    project_id  INTEGER       NOT NULL REFERENCES projects (id),
    work_date   DATE          NOT NULL,
    hours       NUMERIC(4, 2) NOT NULL CHECK (hours > 0 AND hours <= 24),
    note        TEXT          NOT NULL DEFAULT '',
    status      VARCHAR(20)   NOT NULL DEFAULT 'pending' CHECK (status IN ({_in(TIME_ENTRY_STATUSES)})),
    reviewed_by INTEGER REFERENCES users (id),
    reviewed_at TIMESTAMPTZ,
    review_note TEXT          NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS time_entries_user_idx ON time_entries (user_id, work_date);
CREATE INDEX IF NOT EXISTS time_entries_project_idx ON time_entries (project_id, status);

CREATE TABLE IF NOT EXISTS audit_log (
    id         BIGSERIAL PRIMARY KEY,
    actor_id   INTEGER REFERENCES users (id),
    entity     VARCHAR(50) NOT NULL,
    entity_id  INTEGER     NOT NULL,
    action     VARCHAR(50) NOT NULL,
    summary    TEXT        NOT NULL DEFAULT '',
    changes    JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_log_entity_idx ON audit_log (entity, entity_id);
CREATE INDEX IF NOT EXISTS audit_log_created_idx ON audit_log (created_at DESC);

CREATE TABLE IF NOT EXISTS notifications (
    id         BIGSERIAL PRIMARY KEY,
    user_id    INTEGER     NOT NULL REFERENCES users (id),
    audit_id   BIGINT REFERENCES audit_log (id),
    message    TEXT        NOT NULL,
    entity     VARCHAR(50) NOT NULL,
    entity_id  INTEGER     NOT NULL,
    read_at    TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS notifications_user_idx ON notifications (user_id, read_at, created_at DESC);
"""


def ensure_schema(cur) -> None:
    """Create tables if needed and seed the admin account (once per container)."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    cur.execute("SELECT pg_advisory_xact_lock(%s)", [_SCHEMA_LOCK_ID])
    _drop_v1_schema(cur)
    cur.execute(DDL)
    cur.execute(
        "INSERT INTO schema_meta (id, version) VALUES (1, %s) "
        "ON CONFLICT (id) DO UPDATE SET version = EXCLUDED.version",
        [SCHEMA_VERSION],
    )
    seed_admin(cur)
    _SCHEMA_READY = True


def _drop_v1_schema(cur) -> None:
    """Remove version-1 tables (no schema_meta table) so version 2 can be created."""
    cur.execute("SELECT to_regclass('schema_meta') IS NOT NULL AS has_meta, "
                "to_regclass('users') IS NOT NULL AS has_users")
    row = cur.fetchone()
    if row["has_meta"] or not row["has_users"]:
        return
    logger.warning("Rebuilding version-1 development schema as version %s", SCHEMA_VERSION)
    cur.execute("DROP TABLE IF EXISTS " + ", ".join(V1_TABLES) + " CASCADE")
    cur.execute("DROP SEQUENCE IF EXISTS employee_number_seq, project_number_seq")


def reset_schema_flag() -> None:
    """Force the next ensure_schema call to run again (used by tests)."""
    global _SCHEMA_READY
    _SCHEMA_READY = False


def seed_admin(cur) -> None:
    """Create the initial admin from ADMIN_EMAIL / ADMIN_PASSWORD if no such user exists."""
    email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "")
    if not email or not password:
        return
    cur.execute("SELECT 1 FROM users WHERE lower(email) = %s", [email])
    if cur.fetchone():
        return
    employee_id = (os.getenv("ADMIN_EMPLOYEE_ID", "") or "ADMIN001").strip().upper()
    cur.execute(
        """
        INSERT INTO users (employee_id, first_name, last_name, email, job_title, role, password_hash)
        VALUES (%s, 'System', 'Administrator', %s, 'Administrator', 'admin', %s)
        ON CONFLICT DO NOTHING
        """,
        [employee_id, email, hash_password(password)],
    )
    logger.info("Seeded admin account %s", email)
