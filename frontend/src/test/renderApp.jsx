import { render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../App';
import { mockApi, signIn } from './mockApi';

/**
 * Render the whole app at `path`, signed in as `user`, with extra API routes.
 *
 * @returns {{user: ReturnType<typeof userEvent.setup>, fetchMock: import('vitest').Mock}}
 */
export function renderApp({ as, path = '/', routes = {} }) {
  if (as) signIn();
  window.history.replaceState({}, '', path);
  const fetchMock = mockApi({ ...(as ? { 'GET /api/auth/me': as } : {}), ...routes });
  const user = userEvent.setup();
  render(<App />);
  return { user, fetchMock };
}

/** A minimal dashboard response. */
export function dashboard(role, extra = {}) {
  return {
    role,
    projects_total: 3,
    projects_by_status: { planned: 1, active: 2, on_hold: 0, completed: 0 },
    projects_by_health: { green: 1, amber: 1, red: 1 },
    at_risk_projects: [{ id: 7, code: 'PRJ-0007', name: 'Apollo', status: 'active', health: 'red', end_date: '2026-12-01' }],
    upcoming_deliverables: [],
    overdue_deliverables: 2,
    max_weekly_hours: 40,
    ...(role === 'employee'
      ? { my_assignments: [], my_hours: { allocated: 24, remaining: 16 } }
      : {
        pending_requests: 1,
        budget: { budget_total: 1000, planned: 800, actual: 300 },
        capacity: { people: 1, fully_allocated: 0, available_hours: 10, team: [{ id: 3, full_name: 'Eve Employee', job_title: 'Engineer', allocated_hours: 30 }] },
      }),
    ...extra,
  };
}
