/**
 * Typed wrappers around each backend service.
 */
import { request } from './client';

/** Standard list/get/create/update helpers for a service (there are no deletes). */
function crud(service) {
  return {
    list: (query) => request(service, '', { query }),
    get: (id) => request(service, `/${id}`),
    create: (body) => request(service, '', { method: 'POST', body }),
    update: (id, body) => request(service, `/${id}`, { method: 'PUT', body }),
  };
}

const post = (service, path, body) => request(service, path, { method: 'POST', body });

export const authApi = {
  login: (login, password) => request('auth', '/login', { method: 'POST', body: { login, password }, auth: false }),
  me: () => request('auth', '/me'),
};

export const usersApi = {
  ...crud('users'),
  updateMe: (body) => request('users', '/me', { method: 'PUT', body }),
  resetPassword: (id) => post('users', `/${id}/reset-password`),
  workload: (id, query) => request('users', `/${id}/workload`, { query }),
};

export const projectsApi = {
  ...crud('projects'),
  dashboard: () => request('projects', '/dashboard'),
  summary: (id) => request('projects', `/${id}/summary`),
  archive: (id) => post('projects', `/${id}/archive`),
  reactivate: (id) => post('projects', `/${id}/reactivate`),
};

export const requestsApi = {
  ...crud('project-requests'),
  approve: (id, reviewNote) => post('project-requests', `/${id}/approve`, { review_note: reviewNote }),
  reject: (id, reviewNote) => post('project-requests', `/${id}/reject`, { review_note: reviewNote }),
  withdraw: (id) => post('project-requests', `/${id}/withdraw`),
};

export const assignmentsApi = {
  ...crud('assignments'),
  grid: (query) => request('assignments', '/grid', { query }),
  archive: (id) => post('assignments', `/${id}/archive`),
  reactivate: (id) => post('assignments', `/${id}/reactivate`),
};

export const deliverablesApi = {
  ...crud('deliverables'),
  graph: (projectId) => request('deliverables', '/graph', { query: { project_id: projectId } }),
  archive: (id) => post('deliverables', `/${id}/archive`),
  reactivate: (id) => post('deliverables', `/${id}/reactivate`),
};

export const budgetsApi = {
  list: (query) => request('budgets', '', { query }),
  get: (projectId) => request('budgets', `/${projectId}`),
  set: (projectId, budgetCents) => request('budgets', `/${projectId}`, { method: 'PUT', body: { budget_cents: budgetCents } }),
};

export const timesheetsApi = {
  ...crud('timesheets'),
  week: (start) => request('timesheets', '/week', { query: { start } }),
  withdraw: (id) => post('timesheets', `/${id}/withdraw`),
  approve: (id) => post('timesheets', `/${id}/approve`, {}),
  reject: (id, reviewNote) => post('timesheets', `/${id}/reject`, { review_note: reviewNote }),
  approveBatch: (ids) => post('timesheets', '/approve-batch', { ids }),
};

export const activityApi = {
  notifications: (query) => request('activity', '/notifications', { query }),
  markRead: (id) => post('activity', `/notifications/${id}/read`),
  markAllRead: () => post('activity', '/notifications/read-all'),
  audit: (query) => request('activity', '/audit', { query }),
};
