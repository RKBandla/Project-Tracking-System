"""
Timesheets service: employees log hours, managers and admins approve them.

AWS Lambda entry point only. The code is split MVC-style in this folder:
    timesheets_controller.py   routes: check the request, call the model, return a view
    timesheets_model.py        database queries
    timesheets_view.py         JSON responses

Routes (relative to /api/timesheets):
    GET  /                  list entries (employee: own; manager: direct reports; admin: all)
    GET  /week              the caller's week: bookable projects, entries, daily totals (?start=)
    POST /                  log hours {project_id, work_date, hours, note} (employees)
    PUT  /{id}              edit a pending entry (owner)
    POST /{id}/withdraw     withdraw a pending entry (owner) - nothing is deleted
    POST /{id}/approve      approve (admin: anyone; manager: direct reports)
    POST /{id}/reject       reject with a reason
    POST /approve-batch     approve several pending entries {ids: [...]}

Only approved hours count towards a project's consumed cost.
"""

from shared.app import make_handler
from timesheets_controller import router

handler = make_handler(router, "timesheets")
