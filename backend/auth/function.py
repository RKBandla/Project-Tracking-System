"""
Auth service: log in with username (full name) or email and password, refresh tokens, current user.

AWS Lambda entry point only. The code is split MVC-style in this folder:
    auth_controller.py   routes: check the request, call the model, return a view
    auth_model.py        database lookups (shared with other services)
    auth_view.py         JSON responses

Routes (relative to /api/auth):
    POST /login     {login, password}   -> tokens + user   (public)
                    login is "First Last" or an email; {email, password} still works
    POST /refresh   {refresh_token}     -> tokens + user   (public)
    GET  /me                            -> current user
"""

from shared.app import make_handler
from auth_controller import router

handler = make_handler(router, "auth")
