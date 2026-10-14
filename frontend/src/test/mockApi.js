import { vi } from 'vitest';

/**
 * Replace fetch with a router of canned responses.
 *
 * Keys are "METHOD /api/service/path" (query string ignored); values are a
 * response body, a function (request) => body, or {status, body}.
 *
 * @param {object} routes
 * @returns {import('vitest').Mock} the fetch mock (inspect .mock.calls)
 */
export function mockApi(routes) {
  const fetchMock = vi.fn(async (url, options = {}) => {
    const { pathname } = new URL(url, 'http://localhost');
    const key = `${options.method || 'GET'} ${pathname}`;
    if (!(key in routes)) {
      return new Response(JSON.stringify({ error: { message: `No mock for ${key}` } }), { status: 404 });
    }
    let result = routes[key];
    if (typeof result === 'function') {
      result = result({ url, body: options.body ? JSON.parse(options.body) : undefined, headers: options.headers });
    }
    const isWrapped = result && typeof result === 'object' && 'status' in result && 'body' in result;
    const status = isWrapped ? result.status : 200;
    const body = isWrapped ? result.body : result;
    return new Response(status === 204 ? null : JSON.stringify(body), { status });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

/** Store a fake session so the app starts signed in. */
export function signIn() {
  localStorage.setItem('pts.session', JSON.stringify({ access_token: 'access', refresh_token: 'refresh' }));
}

export const USERS = {
  admin: { id: 1, employee_id: 'ADMIN001', first_name: 'Ada', last_name: 'Admin', full_name: 'Ada Admin', email: 'ada@x.com', job_title: 'Administrator', role: 'admin', manager_id: null, salary_cents: null, created_at: '2026-01-01' },
  manager: { id: 2, employee_id: 'EMP0001', first_name: 'Max', last_name: 'Manager', full_name: 'Max Manager', email: 'max@x.com', job_title: 'Eng Manager', role: 'manager', manager_id: 1, salary_cents: 12000000, created_at: '2026-01-01' },
  employee: { id: 3, employee_id: 'EMP0002', first_name: 'Eve', last_name: 'Employee', full_name: 'Eve Employee', email: 'eve@x.com', job_title: 'Engineer', role: 'employee', manager_id: 2, manager_name: 'Max Manager', salary_cents: 8000000, created_at: '2026-01-01' },
};
