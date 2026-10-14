"""
Assignments (resources) service: book people onto projects for N hours per week
over a date range, plus the allocation grid.

AWS Lambda entry point only. The code is split MVC-style in this folder:
    assignments_controller.py   routes: check the request, call the model, return a view
    assignments_model.py        database queries
    assignments_view.py         JSON responses

Routes (relative to /api/assignments):
    GET  /                  list assignments (search, filters, pagination)
    GET  /grid              allocation grid: people down, weeks across (admin, manager)
    POST /                  book a person onto a project
    GET  /{id}              view assignment
    PUT  /{id}              change hours, dates or project role
    POST /{id}/archive      end the booking (nothing is deleted)
    POST /{id}/reactivate   restore an archived booking

Rules:
- admins book anyone onto any project; managers book anyone in the company onto
  projects they manage;
- nobody is booked over 40 hours in any week (409 naming the conflicting projects).
"""

from shared.app import make_handler
from assignments_controller import router

handler = make_handler(router, "assignments")
