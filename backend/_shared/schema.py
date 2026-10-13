"""
Database schema (idempotent) and initial admin seed.

There is no separate migration step in the workshop deployment, so every
service ensures the schema once per Lambda container. A transaction-level
advisory lock serialises concurrent cold starts.
"""

import logging
import os

from .auth import hash_password

logger = logging.getLogger(__name__)

ROLES = ("admin", "manager", "employee")
PROJECT_STATUSES = ("planned", "active", "on_hold", "completed")
PROJECT_HEALTH = ("green", "amber", "red")
REQUEST_STATUSES = ("pending", "approved", "rejected", "withdrawn")
DELIVERABLE_STATUSES = ("todo", "in_progress", "blocked", "done")
BUDGET_CATEGORIES = ("labor", "software", "hardware", "travel", "services", "other")

_SCHEMA_LOCK_ID = 727_001
_SCHEMA_READY = False


def _in(values: tuple) -> str:
    """Render a tuple of constants as a SQL IN list for CHECK constraints."""
    return ", ".join(f"'{v}'" for v in values)


DDL = f"""
CREATE SEQUENCE IF NOT EXISTS employee_number_seq START 1;
CREATE SEQUENCE IF NOT EXISTS project_number_seq START 1;

CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    employee_id   VARCHAR(20)  NOT NULL UNIQUE,
    first_name    VARCHAR(100) NOT NULL,
    last_name     VARCHAR(100) NOT NULL,
    email         VARCHAR(255) NOT NULL,
    job_title     VARCHAR(150) NOT NULL DEFAULT '',
    salary        NUMERIC(12, 2) CHECK (salary IS NULL OR salary >= 0),
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
CREATE INDEX IF NOT EXISTS users_role_idx ON users (role);

CREATE TABLE IF NOT EXISTS projects (
    id           SERIAL PRIMARY KEY,
    code         VARCHAR(20)  NOT NULL UNIQUE,
    name         VARCHAR(200) NOT NULL,
    description  TEXT         NOT NULL DEFAULT '',
    status       VARCHAR(20)  NOT NULL DEFAULT 'planned' CHECK (status IN ({_in(PROJECT_STATUSES)})),
    health       VARCHAR(10)  NOT NULL DEFAULT 'green' CHECK (health IN ({_in(PROJECT_HEALTH)})),
    start_date   DATE,
    end_date     DATE,
    manager_id   INTEGER REFERENCES users (id),
    budget_total NUMERIC(14, 2) NOT NULL DEFAULT 0 CHECK (budget_total >= 0),
    is_archived  BOOLEAN      NOT NULL DEFAULT FALSE,
    archived_at  TIMESTAMPTZ,
    archived_by  INTEGER REFERENCES users (id),
    created_by   INTEGER REFERENCES users (id),
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date)
);
CREATE INDEX IF NOT EXISTS projects_manager_idx ON projects (manager_id);
CREATE INDEX IF NOT EXISTS projects_status_idx ON projects (status, health, is_archived);

CREATE TABLE IF NOT EXISTS project_requests (
    id                  SERIAL PRIMARY KEY,
    requested_by        INTEGER      NOT NULL REFERENCES users (id),
    name                VARCHAR(200) NOT NULL,
    description         TEXT         NOT NULL DEFAULT '',
    justification       TEXT         NOT NULL DEFAULT '',
    proposed_start_date DATE,
    proposed_end_date   DATE,
    proposed_budget     NUMERIC(14, 2) NOT NULL DEFAULT 0 CHECK (proposed_budget >= 0),
    status              VARCHAR(20)  NOT NULL DEFAULT 'pending' CHECK (status IN ({_in(REQUEST_STATUSES)})),
    reviewed_by         INTEGER REFERENCES users (id),
    reviewed_at         TIMESTAMPTZ,
    review_note         TEXT         NOT NULL DEFAULT '',
    project_id          INTEGER REFERENCES projects (id),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS project_requests_requested_by_idx ON project_requests (requested_by, status);

CREATE TABLE IF NOT EXISTS project_assignments (
    id             SERIAL PRIMARY KEY,
    project_id     INTEGER      NOT NULL REFERENCES projects (id),
    user_id        INTEGER      NOT NULL REFERENCES users (id),
    project_role   VARCHAR(100) NOT NULL DEFAULT '',
    hours_per_week INTEGER      NOT NULL CHECK (hours_per_week BETWEEN 1 AND 40),
    assigned_by    INTEGER REFERENCES users (id),
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (project_id, user_id)
);
CREATE INDEX IF NOT EXISTS project_assignments_user_idx ON project_assignments (user_id);

CREATE TABLE IF NOT EXISTS deliverables (
    id           SERIAL PRIMARY KEY,
    project_id   INTEGER      NOT NULL REFERENCES projects (id),
    title        VARCHAR(200) NOT NULL,
    description  TEXT         NOT NULL DEFAULT '',
    status       VARCHAR(20)  NOT NULL DEFAULT 'todo' CHECK (status IN ({_in(DELIVERABLE_STATUSES)})),
    due_date     DATE,
    assignee_id  INTEGER REFERENCES users (id),
    progress_pct INTEGER      NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
    created_by   INTEGER REFERENCES users (id),
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS deliverables_project_idx ON deliverables (project_id, status);
CREATE INDEX IF NOT EXISTS deliverables_assignee_idx ON deliverables (assignee_id);

CREATE TABLE IF NOT EXISTS budget_items (
    id             SERIAL PRIMARY KEY,
    project_id     INTEGER      NOT NULL REFERENCES projects (id),
    category       VARCHAR(20)  NOT NULL CHECK (category IN ({_in(BUDGET_CATEGORIES)})),
    description    VARCHAR(255) NOT NULL,
    planned_amount NUMERIC(14, 2) NOT NULL DEFAULT 0 CHECK (planned_amount >= 0),
    actual_amount  NUMERIC(14, 2) NOT NULL DEFAULT 0 CHECK (actual_amount >= 0),
    entry_date     DATE         NOT NULL DEFAULT CURRENT_DATE,
    created_by     INTEGER REFERENCES users (id),
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS budget_items_project_idx ON budget_items (project_id, category);

CREATE TABLE IF NOT EXISTS audit_log (
    id         BIGSERIAL PRIMARY KEY,
    actor_id   INTEGER REFERENCES users (id),
    entity     VARCHAR(50) NOT NULL,
    entity_id  INTEGER     NOT NULL,
    action     VARCHAR(50) NOT NULL,
    changes    JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_log_entity_idx ON audit_log (entity, entity_id);
"""


def ensure_schema(cur) -> None:
    """Create tables if needed and seed the admin account (once per container)."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    cur.execute("SELECT pg_advisory_xact_lock(%s)", [_SCHEMA_LOCK_ID])
    cur.execute(DDL)
    seed_admin(cur)
    _SCHEMA_READY = True


def reset_schema_flag() -> None:
    """Force the next ensure_schema call to run again (used by tests)."""
    global _SCHEMA_READY
    _SCHEMA_READY = False


def seed_admin(cur) -> None:
    """Create the initial admin from ADMIN_EMPLOYEE_ID / ADMIN_PASSWORD if it is missing."""
    employee_id = os.getenv("ADMIN_EMPLOYEE_ID", "").strip().upper()
    password = os.getenv("ADMIN_PASSWORD", "")
    if not employee_id or not password:
        return
    cur.execute("SELECT 1 FROM users WHERE employee_id = %s", [employee_id])
    if cur.fetchone():
        return
    cur.execute(
        """
        INSERT INTO users (employee_id, first_name, last_name, email, job_title, role, password_hash)
        VALUES (%s, 'System', 'Administrator', %s, 'Administrator', 'admin', %s)
        ON CONFLICT DO NOTHING
        """,
        [employee_id, f"{employee_id.lower()}@pts.local", hash_password(password)],
    )
    logger.info("Seeded admin account %s", employee_id)
