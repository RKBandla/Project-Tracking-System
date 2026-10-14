"""
Activity service: in-app notifications and the audit log.

AWS Lambda entry point only. The code is split MVC-style in this folder:
    activity_controller.py   routes: check the request, call the model, return a view
    activity_model.py        database queries
    activity_view.py         JSON responses

Routes (relative to /api/activity):
    GET  /notifications             the caller's notifications (?unread=true)
    POST /notifications/read-all    mark all as read
    POST /notifications/{id}/read   mark one as read
    GET  /audit                     audit log with search and filters (admin)
"""

from shared.app import make_handler
from activity_controller import router

handler = make_handler(router, "activity")
