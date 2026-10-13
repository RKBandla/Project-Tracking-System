/**
 * Typed wrappers around each backend service.
 */
import { request } from './client';

/** Standard REST helpers for a service. */
function crud(service) {
  return {
    list: (query) => request(service, '', { query }),
    get: (id) => request(service, `/${id}`),
    create: (body) => request(service, '', { method: 'POST', body }),
    update: (id, body) => request(service, `/${id}`, { method: 'PUT', body }),
    remove: (id) => request(service, `/${id}`, { method: 'DELETE' }),
  };
}

export const authApi = {
  login: (employeeId, password) => request('auth', '/login', {
    method: 'POST', body: { employee_id: employeeId, password }, auth: false,
  }),
  me: () => request('auth', '/me'),
};

export const usersApi = {
  ...crud('users'),
  updateMe: (body) => request('users', '/me', { method: 'PUT', body }),
  resetPassword: (id) => request('users', `/${id}/reset-password`, { method: 'POST' }),
  workload: (id) => request('users', `/${id}/workload`),
};

export const projectsApi = {
  ...crud('projects'),
  dashboard: () => request('projects', '/dashboard'),
  summary: (id) => request('projects', `/${id}/summary`),
  archive: (id) => request('projects', `/${id}/archive`, { method: 'POST' }),
  reactivate: (id) => request('projects', `/${id}/reactivate`, { method: 'POST' }),
};

export const requestsApi = {
  ...crud('project-requests'),
  approve: (id, reviewNote) => request('project-requests', `/${id}/approve`, {
    method: 'POST', body: { review_note: reviewNote },
  }),
  reject: (id, reviewNote) => request('project-requests', `/${id}/reject`, {
    method: 'POST', body: { review_note: reviewNote },
  }),
  withdraw: (id) => request('project-requests', `/${id}/withdraw`, { method: 'POST' }),
};

export const assignmentsApi = crud('assignments');
export const deliverablesApi = crud('deliverables');
export const budgetsApi = crud('budgets');
