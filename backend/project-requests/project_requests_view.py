"""
Project requests VIEW: the JSON shapes the project requests service sends back.
"""

from shared.http import response
from shared.projects import present_project


def request_list(result: dict) -> dict:
    """A page of project requests."""
    return response(200, result)


def request(row: dict, status: int = 200) -> dict:
    """Response with one project request."""
    return response(status, row)


def approved(row: dict, project: dict) -> dict:
    """An approved request together with the project created for it."""
    return response(200, {"request": row, "project": present_project(project)})
