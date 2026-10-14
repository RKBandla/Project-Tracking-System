"""
Deliverables service: work items on a project, with "depends on" links.

AWS Lambda entry point only. The code is split MVC-style in this folder:
    deliverables_controller.py   routes: check the request, call the model, return a view
    deliverables_model.py        database queries
    deliverables_view.py         JSON responses

Routes (relative to /api/deliverables):
    GET  /                  list deliverables on visible projects (search, filters, sort)
    GET  /graph             dependency graph for one project (?project_id=)
    POST /                  create deliverable (admin, or the project's manager)
    GET  /{id}              view deliverable
    PUT  /{id}              update deliverable, including ``depends_on`` (list of ids)
    POST /{id}/archive      archive (nothing is deleted)
    POST /{id}/reactivate   restore an archived deliverable

Rules:
- dependencies must be on the same project and can't form a loop;
- a deliverable can't be marked done while something it depends on isn't done;
- a milestone (``is_milestone``) is a checkpoint with a single date: it needs a
  due date and has no separate start date.
"""

from shared.app import make_handler
from deliverables_controller import router

handler = make_handler(router, "deliverables")
