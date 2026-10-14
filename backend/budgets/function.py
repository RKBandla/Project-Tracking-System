"""
Budgets service: one budget per project, compared with planned and consumed cost.

    hourly rate   = annual salary / 2080
    planned cost  = sum(hours per week x weeks in assignment x hourly rate)
    consumed cost = sum(approved logged hours x hourly rate)

AWS Lambda entry point only. The code is split MVC-style in this folder:
    budgets_controller.py   routes: check the request, call the model, return a view
    budgets_model.py        database queries
    budgets_view.py         JSON responses

Routes (relative to /api/budgets):
    GET /         budgets of visible projects (search, at-risk filter, pagination)
    GET /{id}     one project's budget, with per-person breakdown for admins and its manager
    PUT /{id}     set the budget {budget_cents} (admin, or the project's manager)

All amounts are whole cents. Employees see totals for projects they are assigned
to, but never per-person costs (they reveal salaries).
"""

from shared.app import make_handler
from budgets_controller import router

handler = make_handler(router, "budgets")
