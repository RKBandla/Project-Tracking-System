"""
Projects service: projects, archiving, health summary and dashboard.

AWS Lambda entry point only. The code is split MVC-style in this folder:
    projects_controller.py   routes: check the request, call the model, return a view
    projects_model.py        database queries
    projects_view.py         JSON responses

Routes (relative to /api/projects):
    GET  /                  list visible projects (search, filters, sort, pagination)
    POST /                  create project (admin)
    GET  /dashboard         role-specific overview
    GET  /{id}              view project (with cost and risk metrics)
    PUT  /{id}              update (admin: all fields; manager: description and status)
    POST /{id}/archive      archive project (admin) - nothing is ever deleted
    POST /{id}/reactivate   reactivate archived project (admin)
    GET  /{id}/summary      deliverable, budget, team and risk metrics

Visibility: admins see all projects, managers the projects they manage and
employees the projects they are assigned to.
"""

from shared.app import make_handler
from projects_controller import router

handler = make_handler(router, "projects")
