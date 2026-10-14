"""
Project requests service: managers ask admins to create projects.

AWS Lambda entry point only. The code is split MVC-style in this folder:
    project_requests_controller.py   routes: check the request, call the model, return a view
    project_requests_model.py        database queries
    project_requests_view.py         JSON responses

Routes (relative to /api/project-requests):
    GET  /                 list requests (admin: all, manager: own)
    POST /                 submit a request (manager)
    GET  /{id}             view request (admin or requester)
    PUT  /{id}             edit a pending request (requester)
    POST /{id}/withdraw    withdraw a pending request (requester)
    POST /{id}/approve     approve and create the project with the requester as manager (admin)
    POST /{id}/reject      reject with a note (admin)
"""

from shared.app import make_handler
from project_requests_controller import router

handler = make_handler(router, "project-requests")
