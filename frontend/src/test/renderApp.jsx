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
  const fetchMock = mockApi({
    'GET /api/activity/notifications': NO_NOTIFICATIONS,
    ...(as ? { 'GET /api/auth/me': as } : {}),
    ...routes,
  });
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
    at_risk_count: 1,
    at_risk_projects: [{
      id: 7, code: 'PRJ-0007', name: 'Apollo', status: 'active', end_date: '2026-12-01', manager_name: 'Max Manager',
      risk_reasons: ['2 overdue deliverables'],
    }],
    upcoming_deliverables: [],
    overdue_deliverables: 2,
    max_weekly_hours: 40,
    budget: { budget_cents: 100000, planned_cents: 80000, consumed_cents: 30000 },
    unread_notifications: 0,
    ...(role === 'employee'
      ? { my_assignments: [], my_week_hours: 24, my_logged_this_week: { pending: 4, approved: 8 } }
      : {
        pending_requests: 1,
        hours_to_approve: 3,
        fully_booked_people: [{ id: 3, full_name: 'Eve Employee', job_title: 'Engineer', peak_hours: 40 }],
      }),
    ...extra,
  };
}

/** Default response for the unread-notifications badge. */
export const NO_NOTIFICATIONS = { items: [], total: 0, page: 1, page_size: 1, unread: 0 };
