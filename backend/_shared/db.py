"""
PostgreSQL connection management.

A single module-level connection is reused across invocations of the same
Lambda container (same strategy as backend/_examples/python-service). Each
request runs inside one transaction so it is applied atomically.
"""

import logging
import os
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

# Module-level connection persisted between invocations of a warm container
_CONN: psycopg.Connection | None = None


def conninfo() -> str:
    """Build the connection string from the standard workshop environment variables."""
    params = {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": os.getenv("POSTGRES_PORT", "5432"),
        "user": os.getenv("POSTGRES_USER", "postgres"),
        "password": os.getenv("POSTGRES_PASS", "postgres123"),
        "dbname": os.getenv("POSTGRES_NAME", "postgres"),
        "connect_timeout": "15",
    }
    # Aurora requires TLS; the local PostgreSQL does not
    if os.getenv("IS_LOCAL", "true") != "true":
        params["sslmode"] = "require"
    return make_conninfo(**params)


def get_conn() -> psycopg.Connection:
    """Return the pooled connection, (re)connecting when needed."""
    global _CONN
    if _CONN is None or _CONN.closed or _CONN.broken:
        _CONN = psycopg.connect(conninfo(), autocommit=True, row_factory=dict_row)
    return _CONN


def reset() -> None:
    """Drop the pooled connection so the next call reconnects."""
    global _CONN
    if _CONN is not None:
        try:
            _CONN.close()
        except psycopg.Error:
            pass
    _CONN = None


@contextmanager
def cursor() -> Iterator[psycopg.Cursor]:
    """Yield a dict-row cursor inside a transaction that commits on success."""
    conn = get_conn()
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                yield cur
    except psycopg.OperationalError:
        logger.exception("Database connection error; resetting connection")
        reset()
        raise
