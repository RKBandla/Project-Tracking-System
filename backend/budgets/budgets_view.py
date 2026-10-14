"""
Budgets VIEW: the JSON shapes the budgets service sends back.

Per-person figures are only added by the controller for admins and the
project's manager (they reveal salaries).
"""

from shared.http import response
from shared.projects import present_project

FIELDS = ("id", "code", "name", "status", "start_date", "end_date", "manager_id", "manager_name", "is_archived",
          "budget_cents", "planned_cents", "consumed_cents", "consumed_share", "elapsed_share", "over_burn",
          "at_risk", "risk_reasons")


def summary(project: dict) -> dict:
    """Budget figures for one (presented) project."""
    data = {k: project[k] for k in FIELDS}
    data["remaining_cents"] = project["budget_cents"] - project["consumed_cents"]
    data["unplanned_cents"] = project["budget_cents"] - project["planned_cents"]
    return data


def budget_list(result: dict) -> dict:
    """A page of project budgets."""
    result["items"] = [summary(present_project(p)) for p in result["items"]]
    return response(200, result)


def budget(result: dict) -> dict:
    """Response with one project's budget (and breakdowns, when included)."""
    return response(200, result)
