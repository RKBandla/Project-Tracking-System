"""
Project requests MODEL: every database query for project requests.

Only this file talks to the ``project_requests`` table for the project
requests service. The controller calls these functions; nothing here knows
about HTTP.
"""

from shared.projects import get_project, insert_project  # project lookups shared with other services
from shared.query import Filters, paginated
from shared.users import get_user  # user lookup shared with other services

__all__ = ["get_project", "insert_project", "get_user", "list_requests", "get_request", "insert_request",
           "update_request", "withdraw_request", "approve_request", "reject_request"]

SELECT = """
    SELECT r.*,
           u.first_name || ' ' || u.last_name AS requested_by_name,
           CASE WHEN v.id IS NULL THEN NULL ELSE v.first_name || ' ' || v.last_name END AS reviewed_by_name,
           p.code AS project_code
    FROM project_requests r
    JOIN users u ON u.id = r.requested_by
    LEFT JOIN users v ON v.id = r.reviewed_by
    LEFT JOIN projects p ON p.id = r.project_id
"""
SORTS = {"created_at": "created_at", "name": "name", "status": "status",
         "proposed_budget_cents": "proposed_budget_cents", "proposed_start_date": "proposed_start_date"}


def list_requests(cur, filters: Filters, order_sql: str, query: dict) -> dict:
    """One page of project requests."""
    return paginated(cur, SELECT, filters, order_sql, query)


def get_request(cur, request_id: int, lock: bool = False) -> dict | None:
    """One project request with requester, reviewer and project code, or None (optionally locked)."""
    if lock:
        cur.execute("SELECT id FROM project_requests WHERE id = %s FOR UPDATE", [request_id])
    cur.execute(SELECT + " WHERE r.id = %s", [request_id])
    return cur.fetchone()


def insert_request(cur, requested_by: int, data: dict) -> int:
    """Insert a project request and return the new id."""
    cur.execute(
        """
        INSERT INTO project_requests (requested_by, name, description, justification,
                                      proposed_start_date, proposed_end_date, proposed_budget_cents)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        [requested_by, data["name"], data["description"] or "", data["justification"] or "",
         data["proposed_start_date"], data["proposed_end_date"], data["proposed_budget_cents"] or 0],
    )
    return cur.fetchone()["id"]


def update_request(cur, request_id: int, data: dict) -> None:
    """Update the given columns of a request (column names come from a validated schema)."""
    assignments = ", ".join(f"{name} = %s" for name in data)
    cur.execute(f"UPDATE project_requests SET {assignments}, updated_at = now() WHERE id = %s",  # nosec B608
                [*data.values(), request_id])


def withdraw_request(cur, request_id: int) -> None:
    """Mark a request as withdrawn."""
    cur.execute("UPDATE project_requests SET status = 'withdrawn', updated_at = now() WHERE id = %s", [request_id])


def approve_request(cur, request_id: int, reviewer_id: int, note: str, project_id: int) -> None:
    """Mark a request as approved, linking the project created for it."""
    cur.execute(
        """UPDATE project_requests SET status = 'approved', reviewed_by = %s, reviewed_at = now(),
                  review_note = %s, project_id = %s, updated_at = now() WHERE id = %s""",
        [reviewer_id, note, project_id, request_id],
    )


def reject_request(cur, request_id: int, reviewer_id: int, note: str) -> None:
    """Mark a request as rejected with the reviewer's note."""
    cur.execute(
        """UPDATE project_requests SET status = 'rejected', reviewed_by = %s, reviewed_at = now(),
                  review_note = %s, updated_at = now() WHERE id = %s""",
        [reviewer_id, note, request_id],
    )
