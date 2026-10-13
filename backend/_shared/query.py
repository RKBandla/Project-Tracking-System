"""
Search, filter, sort and pagination helpers for list endpoints.

Only whitelisted column expressions are ever interpolated into SQL; all
user-supplied values are passed as query parameters.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .errors import bad_request

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def like_pattern(text: str) -> str:
    """Escape LIKE wildcards and wrap the term for a contains-search."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def int_param(query: dict, name: str) -> int | None:
    """Read an optional integer query parameter."""
    value = query.get(name)
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise bad_request("Validation failed", {name: "must be an integer"}) from exc


def date_param(query: dict, name: str) -> date | None:
    """Read an optional ISO date query parameter."""
    value = query.get(name)
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise bad_request("Validation failed", {name: "must be a date (YYYY-MM-DD)"}) from exc


def choice_param(query: dict, name: str, choices: tuple) -> str | None:
    """Read an optional query parameter restricted to a set of values."""
    value = query.get(name)
    if value in (None, ""):
        return None
    if value not in choices:
        raise bad_request("Validation failed", {name: f"must be one of: {', '.join(choices)}"})
    return value


@dataclass
class Filters:
    """Accumulates WHERE clauses and their parameters."""

    clauses: list[str] = field(default_factory=list)
    params: list[Any] = field(default_factory=list)

    def add(self, clause: str, *params: Any) -> "Filters":
        """Add a clause (with ``%s`` placeholders) and its parameters."""
        self.clauses.append(clause)
        self.params.extend(params)
        return self

    def eq(self, column: str, value: Any) -> "Filters":
        """Add ``column = value`` when value is not None."""
        if value is not None:
            self.add(f"{column} = %s", value)
        return self

    def search(self, columns: list[str], text: str | None) -> "Filters":
        """Add a case-insensitive contains-search across several columns."""
        if text and text.strip():
            pattern = like_pattern(text.strip())
            ors = " OR ".join(f"{col} ILIKE %s" for col in columns)
            self.add(f"({ors})", *([pattern] * len(columns)))
        return self

    def where(self) -> str:
        """Render the WHERE clause (empty string when there are no filters)."""
        return ("WHERE " + " AND ".join(self.clauses)) if self.clauses else ""


def order_by(query: dict, allowed: dict[str, str], default: str) -> str:
    """
    Build an ORDER BY clause from ``?sort=field`` or ``?sort=-field``.

    Args:
        query: Query string parameters.
        allowed: Public sort keys mapped to SQL expressions.
        default: Default sort key (may start with ``-``).
    """
    sort = query.get("sort") or default
    descending = sort.startswith("-")
    key = sort.lstrip("-")
    if key not in allowed:
        raise bad_request("Validation failed", {"sort": f"must be one of: {', '.join(sorted(allowed))}"})
    direction = "DESC" if descending else "ASC"
    return f"ORDER BY {allowed[key]} {direction} NULLS LAST, id {direction}"


def pagination(query: dict) -> tuple[int, int]:
    """Return (page, page_size) from the query string with sane bounds."""
    page = int_param(query, "page")
    page = 1 if page is None else page
    page_size = int_param(query, "page_size")
    page_size = DEFAULT_PAGE_SIZE if page_size is None else page_size
    if page < 1:
        raise bad_request("Validation failed", {"page": "must be at least 1"})
    if page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise bad_request("Validation failed", {"page_size": f"must be between 1 and {MAX_PAGE_SIZE}"})
    return page, page_size


def paginated(cur, select_sql: str, filters: Filters, order_sql: str, query: dict) -> dict:
    """
    Run a filtered, sorted and paginated list query.

    ``select_sql`` is a trusted ``SELECT ... FROM ...`` statement (no WHERE);
    it is wrapped so filters can reference any of its output columns.
    """
    page, page_size = pagination(query)
    sql = (
        f"SELECT *, count(*) OVER() AS _total FROM ({select_sql}) AS t "  # nosec B608 - trusted fragments
        f"{filters.where()} {order_sql} LIMIT %s OFFSET %s"
    )
    cur.execute(sql, [*filters.params, page_size, (page - 1) * page_size])
    rows = cur.fetchall()
    total = rows[0]["_total"] if rows else _count(cur, select_sql, filters)
    for row in rows:
        row.pop("_total", None)
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


def _count(cur, select_sql: str, filters: Filters) -> int:
    """Count matching rows (used when the requested page is past the end)."""
    sql = f"SELECT count(*) AS n FROM ({select_sql}) AS t {filters.where()}"  # nosec B608
    cur.execute(sql, filters.params)
    return cur.fetchone()["n"]
