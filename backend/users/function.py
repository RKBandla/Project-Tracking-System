"""
Users service: accounts, profiles and workload.

AWS Lambda entry point only. The code is split MVC-style in this folder:
    users_controller.py   routes: check the request, call the model, return a view
    users_model.py        database queries
    users_view.py         JSON responses

Routes (relative to /api/users):
    GET  /                       people directory (admin, manager)
    POST /                       create user (admin) -> generated employee ID + 6-char password
    GET  /me                     own profile
    PUT  /me                     update own first name, last name and email only
    GET  /{id}                   view user (admin, manager, or self)
    PUT  /{id}                   update user (admin; nobody changes their own role or salary)
    POST /{id}/reset-password    generate a new 6-char password (admin)
    GET  /{id}/workload          booked hours per week and assignments

Users are never deleted; admins deactivate them with ``is_active: false``.
Salaries are whole cents and visible to admins, the person's manager and the person.
"""

from shared.app import make_handler
from users_controller import router

handler = make_handler(router, "users")
