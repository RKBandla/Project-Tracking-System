/**
 * Enum values shared with the backend (backend/_shared/schema.py).
 */
export const PROJECT_STATUSES = ['planned', 'active', 'on_hold', 'completed'];
export const DELIVERABLE_STATUSES = ['todo', 'in_progress', 'blocked', 'done'];
export const REQUEST_STATUSES = ['pending', 'approved', 'rejected', 'withdrawn'];
export const TIME_ENTRY_STATUSES = ['pending', 'approved', 'rejected', 'withdrawn'];
export const AUDIT_ENTITIES = ['user', 'project', 'project_request', 'assignment', 'deliverable', 'time_entry'];
