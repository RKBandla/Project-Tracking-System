"""
Deliverables VIEW: the JSON shapes the deliverables service sends back.
"""

from shared.http import response


def deliverable(row: dict, status: int = 200) -> dict:
    """Response with one deliverable."""
    return response(status, row)


def deliverable_list(result: dict) -> dict:
    """A page of deliverables."""
    return response(200, result)


def graph(project_id: int, nodes: list[dict], edges: list[dict]) -> dict:
    """A project's dependency graph: nodes (with levels) and edges."""
    return response(200, {"project_id": project_id, "nodes": nodes, "edges": edges})
