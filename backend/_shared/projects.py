"""
Project persistence shared by the projects and project-requests services.
"""


def insert_project(cur, actor_id: int, data: dict) -> int:
    """Insert a project with a generated code (PRJ-0001, ...) and return its id."""
    cur.execute("SELECT nextval('project_number_seq') AS n")
    code = f"PRJ-{cur.fetchone()['n']:04d}"
    cur.execute(
        """
        INSERT INTO projects (code, name, description, status, health, start_date, end_date,
                              manager_id, budget_total, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        [code, data["name"], data.get("description") or "", data.get("status") or "planned",
         data.get("health") or "green", data.get("start_date"), data.get("end_date"),
         data.get("manager_id"), data.get("budget_total") or 0, actor_id],
    )
    return cur.fetchone()["id"]
