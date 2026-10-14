"""
User lookups and serialisation shared by several services.
"""

USER_SELECT = """
    SELECT u.id, u.employee_id, u.first_name, u.last_name, u.email, u.job_title,
           u.salary_cents, u.role, u.manager_id, u.is_active, u.created_at, u.updated_at,
           u.password_hash,
           CASE WHEN m.id IS NULL THEN NULL ELSE m.first_name || ' ' || m.last_name END AS manager_name
    FROM users u
    LEFT JOIN users m ON m.id = u.manager_id
"""


def get_user(cur, user_id: int, lock: bool = False) -> dict | None:
    """Fetch one user (including password hash) or None."""
    if lock:
        cur.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", [user_id])
    cur.execute(USER_SELECT + " WHERE u.id = %s", [user_id])
    return cur.fetchone()


def get_user_by_email(cur, email: str) -> dict | None:
    """Fetch one user by email (case-insensitive) or None."""
    cur.execute(USER_SELECT + " WHERE lower(u.email) = %s", [email.strip().lower()])
    return cur.fetchone()


def get_users_by_name(cur, full_name: str) -> list[dict]:
    """Fetch every user whose "first last" name matches (case-insensitive, spaces collapsed)."""
    cur.execute(USER_SELECT + " WHERE lower(u.first_name || ' ' || u.last_name) = %s ORDER BY u.id",
                [" ".join(full_name.lower().split())])
    return cur.fetchall()


def _letters(text: str) -> str:
    """Lower-case letters and digits only ("O'Neil" -> "oneil")."""
    return "".join(c for c in text.lower() if c.isalnum())


def email_matches_name(email: str, first_name: str, last_name: str) -> bool:
    """
    The part before @ must be the full name or the initials. Dots, dashes and
    underscores are ignored, so Eli Engineer may use eli.engineer@, eliengineer@ or ee@.
    """
    local = _letters(email.split("@", 1)[0])
    first, last = _letters(first_name), _letters(last_name)
    if not first or not last:
        return False
    return local in (first + last, first[0] + last[0])


def email_rule_hint(first_name: str, last_name: str) -> str:
    """Error message showing the allowed forms for this person's email."""
    first, last = _letters(first_name), _letters(last_name)
    if not first or not last:
        return "must be made from the first and last name"
    return f"must be the full name or the initials, e.g. {first}.{last}@… or {first[0]}{last[0]}@…"


def can_view_salary(viewer: dict, user: dict) -> bool:
    """Admins see all salaries, managers see their direct reports', users see their own."""
    return (
        viewer["role"] == "admin"
        or viewer["id"] == user["id"]
        or (viewer["role"] == "manager" and user.get("manager_id") == viewer["id"])
    )


def serialize_user(user: dict, viewer: dict | None = None) -> dict:
    """Return a public representation of a user, hiding secrets and restricted fields."""
    data = {k: v for k, v in user.items() if k != "password_hash"}
    data["full_name"] = f"{user['first_name']} {user['last_name']}"
    if viewer is not None and not can_view_salary(viewer, user):
        data.pop("salary_cents", None)
    return data


def manager_chain(cur, user_id: int) -> list[int]:
    """Ids of everyone above a user in the reporting line (nearest first)."""
    cur.execute(
        """
        WITH RECURSIVE chain AS (
            SELECT manager_id AS id, 1 AS depth FROM users WHERE id = %s
            UNION
            SELECT u.manager_id, c.depth + 1 FROM users u JOIN chain c ON u.id = c.id
            WHERE c.depth < 20
        )
        SELECT id FROM chain WHERE id IS NOT NULL ORDER BY depth
        """,
        [user_id],
    )
    return [row["id"] for row in cur.fetchall()]


def next_employee_id(cur) -> str:
    """Generate the next unique employee ID (EMP0001, EMP0002, ...)."""
    while True:
        cur.execute("SELECT nextval('employee_number_seq') AS n")
        candidate = f"EMP{cur.fetchone()['n']:04d}"
        cur.execute("SELECT 1 FROM users WHERE employee_id = %s", [candidate])
        if not cur.fetchone():
            return candidate
