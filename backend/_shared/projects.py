"""
Project persistence, cost calculations and the at-risk rule.

Money rules (all amounts are whole cents):
    hourly rate   = annual salary / 2080            (40 h x 52 weeks)
    planned cost  = sum(hours per week x weeks in assignment x hourly rate)
    consumed cost = sum(approved logged hours x hourly rate)

A project is at risk when it is not archived and any of these hold:
    - it is past its end date and not completed
    - a (non-archived) deliverable is overdue
    - consumed share of budget > elapsed share of schedule + 15%
"""

HOURS_PER_YEAR = 2080
BURN_TOLERANCE = 0.15

# Per-row cost expressions, rounded to whole cents. Expect aliases a (assignment),
# t (time entry) and u (the person).
PLANNED_COST_SQL = (
    "ROUND(a.hours_per_week * ((a.end_date - a.start_date + 1) / 7.0) "
    f"* COALESCE(u.salary_cents, 0) / {HOURS_PER_YEAR}.0)::bigint"
)
CONSUMED_COST_SQL = f"ROUND(t.hours * COALESCE(u.salary_cents, 0) / {HOURS_PER_YEAR}.0)::bigint"

# Built only from constant SQL fragments; no request data is interpolated.
_BASE = f"""
    SELECT p.*,
           CASE WHEN m.id IS NULL THEN NULL ELSE m.first_name || ' ' || m.last_name END AS manager_name,
           (SELECT count(DISTINCT a.user_id) FROM project_assignments a
             WHERE a.project_id = p.id AND NOT a.is_archived AND a.end_date >= CURRENT_DATE) AS team_size,
           (SELECT count(*) FROM deliverables d WHERE d.project_id = p.id AND NOT d.is_archived) AS deliverable_count,
           (SELECT count(*) FROM deliverables d
             WHERE d.project_id = p.id AND NOT d.is_archived AND d.status = 'done') AS deliverables_done,
           (SELECT count(*) FROM deliverables d
             WHERE d.project_id = p.id AND NOT d.is_archived AND d.status <> 'done'
               AND d.due_date < CURRENT_DATE) AS overdue_deliverables,
           COALESCE((SELECT SUM({PLANNED_COST_SQL}) FROM project_assignments a JOIN users u ON u.id = a.user_id
                      WHERE a.project_id = p.id AND NOT a.is_archived), 0)::bigint AS planned_cents,
           COALESCE((SELECT SUM({CONSUMED_COST_SQL}) FROM time_entries t JOIN users u ON u.id = t.user_id
                      WHERE t.project_id = p.id AND t.status = 'approved'), 0)::bigint AS consumed_cents
    FROM projects p
    LEFT JOIN users m ON m.id = p.manager_id
"""  # nosec B608

# Built only from constant SQL fragments; no request data is interpolated.
_SHARES = f"""
    SELECT b.*,
           (b.status <> 'completed' AND b.end_date IS NOT NULL AND b.end_date < CURRENT_DATE) AS past_end_date,
           CASE WHEN b.start_date IS NULL OR b.end_date IS NULL OR b.end_date <= b.start_date THEN NULL
                ELSE LEAST(GREATEST((CURRENT_DATE - b.start_date)::numeric / (b.end_date - b.start_date), 0), 1)
           END AS elapsed_share,
           CASE WHEN b.budget_cents > 0 THEN b.consumed_cents::numeric / b.budget_cents END AS consumed_share
    FROM ({_BASE}) AS b
"""  # nosec B608

# Every project column plus metrics, ``over_burn`` and ``at_risk``; wrap with
# ``SELECT * FROM (PROJECT_SELECT) AS pr WHERE ...`` to filter.
# Built only from constant SQL fragments; no request data is interpolated.
PROJECT_SELECT = f"""
    SELECT s.*,
           (s.consumed_share IS NOT NULL
            AND s.consumed_share > COALESCE(s.elapsed_share, 1) + {BURN_TOLERANCE}) AS over_burn,
           (NOT s.is_archived AND (
               s.past_end_date OR s.overdue_deliverables > 0
               OR (s.consumed_share IS NOT NULL
                   AND s.consumed_share > COALESCE(s.elapsed_share, 1) + {BURN_TOLERANCE})
           )) AS at_risk
    FROM ({_SHARES}) AS s
"""  # nosec B608


def risk_reasons(project: dict) -> list[str]:
    """Human-readable reasons a project is at risk (empty when on track)."""
    if project.get("is_archived"):
        return []
    reasons = []
    if project.get("past_end_date"):
        reasons.append(f"Past its end date ({project['end_date'].isoformat()}) and not completed")
    overdue = project.get("overdue_deliverables") or 0
    if overdue:
        reasons.append(f"{overdue} overdue deliverable{'s' if overdue != 1 else ''}")
    if project.get("over_burn"):
        consumed = float(project["consumed_share"]) * 100
        elapsed = float(project["elapsed_share"] if project["elapsed_share"] is not None else 1) * 100
        reasons.append(f"{consumed:.0f}% of budget consumed but only {elapsed:.0f}% of schedule elapsed")
    return reasons


def present_project(project: dict) -> dict:
    """Add risk reasons and convert ratio columns to plain floats for JSON."""
    data = dict(project)
    data["risk_reasons"] = risk_reasons(project)
    for key in ("elapsed_share", "consumed_share"):
        if data.get(key) is not None:
            data[key] = round(float(data[key]), 4)
    return data


def get_project(cur, project_id: int, lock: bool = False) -> dict | None:
    """Fetch a project with metrics, optionally locking the row first."""
    if lock:
        cur.execute("SELECT id FROM projects WHERE id = %s FOR UPDATE", [project_id])
    cur.execute(f"SELECT * FROM ({PROJECT_SELECT}) AS pr WHERE pr.id = %s", [project_id])  # nosec B608
    return cur.fetchone()


def insert_project(cur, actor_id: int, data: dict) -> int:
    """Insert a project with a generated code (PRJ-0001, ...) and return its id."""
    cur.execute("SELECT nextval('project_number_seq') AS n")
    code = f"PRJ-{cur.fetchone()['n']:04d}"
    cur.execute(
        """
        INSERT INTO projects (code, name, description, status, start_date, end_date,
                              manager_id, budget_cents, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        [code, data["name"], data.get("description") or "", data.get("status") or "planned",
         data.get("start_date"), data.get("end_date"), data.get("manager_id"),
         data.get("budget_cents") or 0, actor_id],
    )
    return cur.fetchone()["id"]
