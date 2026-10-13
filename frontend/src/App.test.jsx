import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { USERS } from './test/mockApi';
import { dashboard, renderApp } from './test/renderApp';

describe('authentication', () => {
  it('shows the login page when signed out and signs in with email', async () => {
    const { user, fetchMock } = renderApp({
      routes: {
        'POST /api/auth/login': ({ body }) => (body.password === 'abc123'
          ? { access_token: 'a', refresh_token: 'r', user: USERS.manager }
          : { status: 401, body: { error: { message: 'Invalid email or password' } } }),
        'GET /api/projects/dashboard': dashboard('manager'),
      },
    });

    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Email/), 'max@x.com');
    await user.type(screen.getByLabelText(/Password/), 'wrong1');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByText('Invalid email or password')).toBeInTheDocument();

    await user.clear(screen.getByLabelText(/Password/));
    await user.type(screen.getByLabelText(/Password/), 'abc123');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('heading', { name: 'Welcome back, Max' })).toBeInTheDocument();
    const loginCall = fetchMock.mock.calls.findLast(([url]) => url.endsWith('/api/auth/login'));
    expect(JSON.parse(loginCall[1].body)).toEqual({ email: 'max@x.com', password: 'abc123' });
  });

  it('signs out', async () => {
    const { user } = renderApp({ as: USERS.employee, routes: { 'GET /api/projects/dashboard': dashboard('employee') } });
    await user.click(await screen.findByRole('button', { name: 'Sign out' }));
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(localStorage.getItem('pts.session')).toBeNull();
  });
});

describe('navigation by role', () => {
  const navLabels = async () => {
    const nav = await screen.findByRole('navigation', { name: 'Main' });
    return within(nav).getAllByRole('link').map((a) => a.textContent);
  };

  it('admin', async () => {
    renderApp({ as: USERS.admin, routes: { 'GET /api/projects/dashboard': dashboard('admin') } });
    expect(await navLabels()).toEqual(['Dashboard', 'Projects', 'Allocation', 'Hours to approve', 'Project requests',
      'People', 'Notifications', 'Audit log', 'My profile']);
  });

  it('manager', async () => {
    renderApp({ as: USERS.manager, routes: { 'GET /api/projects/dashboard': dashboard('manager') } });
    expect(await navLabels()).toEqual(['Dashboard', 'Projects', 'Allocation', 'Hours to approve', 'My requests',
      'People', 'Notifications', 'My profile']);
  });

  it('employee', async () => {
    renderApp({ as: USERS.employee, routes: { 'GET /api/projects/dashboard': dashboard('employee') } });
    expect(await navLabels()).toEqual(['Dashboard', 'My projects', 'My timesheet', 'Notifications', 'My profile']);
  });

  it('shows the unread notification count', async () => {
    renderApp({
      as: USERS.manager,
      routes: {
        'GET /api/projects/dashboard': dashboard('manager'),
        'GET /api/activity/notifications': { items: [], total: 3, page: 1, page_size: 1, unread: 3 },
      },
    });
    expect(await screen.findByLabelText('3 unread')).toBeInTheDocument();
  });

  it('blocks pages a role cannot open and shows not found', async () => {
    renderApp({ as: USERS.employee, path: '/audit' });
    expect(await screen.findByText('You do not have access to this page')).toBeInTheDocument();
  });

  it('shows not found', async () => {
    renderApp({ as: USERS.admin, path: '/nope' });
    expect(await screen.findByText('Page not found')).toBeInTheDocument();
  });
});

describe('dashboard', () => {
  it('shows at-risk projects with their reasons', async () => {
    renderApp({ as: USERS.admin, routes: { 'GET /api/projects/dashboard': dashboard('admin') } });
    expect(await screen.findByText('2 overdue deliverables')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Apollo/ })).toHaveAttribute('href', '/projects/7');
    expect(screen.getByRole('img', { name: /\$300 consumed and \$800 planned of a \$1,000 budget/ })).toBeInTheDocument();
    expect(screen.getByText('Eve Employee')).toBeInTheDocument();
  });

  it('employee sees bookings and logged hours', async () => {
    renderApp({ as: USERS.employee, routes: { 'GET /api/projects/dashboard': dashboard('employee') } });
    expect(await screen.findByText('24 h')).toBeInTheDocument();
    expect(screen.getByText('4 h pending · 8 h approved')).toBeInTheDocument();
  });
});
