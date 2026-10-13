import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { USERS } from './test/mockApi';
import { dashboard, renderApp } from './test/renderApp';

describe('authentication', () => {
  it('shows the login page when signed out and signs in with employee ID', async () => {
    const { user, fetchMock } = renderApp({
      routes: {
        'POST /api/auth/login': ({ body }) => (body.password === 'abc123'
          ? { access_token: 'a', refresh_token: 'r', user: USERS.manager }
          : { status: 401, body: { error: { message: 'Invalid employee ID or password' } } }),
        'GET /api/projects/dashboard': dashboard('manager'),
      },
    });

    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Employee ID/), 'EMP0001');
    await user.type(screen.getByLabelText(/Password/), 'wrong1');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByText('Invalid employee ID or password')).toBeInTheDocument();

    await user.clear(screen.getByLabelText(/Password/));
    await user.type(screen.getByLabelText(/Password/), 'abc123');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('heading', { name: 'Welcome back, Max' })).toBeInTheDocument();
    const loginCall = fetchMock.mock.calls.findLast(([url]) => url.endsWith('/api/auth/login'));
    expect(JSON.parse(loginCall[1].body)).toEqual({ employee_id: 'EMP0001', password: 'abc123' });
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
    expect(await navLabels()).toEqual(['Dashboard', 'Projects', 'Project requests', 'Users', 'My profile']);
  });

  it('manager', async () => {
    renderApp({ as: USERS.manager, routes: { 'GET /api/projects/dashboard': dashboard('manager') } });
    expect(await navLabels()).toEqual(['Dashboard', 'Projects', 'My requests', 'My team', 'My profile']);
  });

  it('employee', async () => {
    renderApp({ as: USERS.employee, routes: { 'GET /api/projects/dashboard': dashboard('employee') } });
    expect(await navLabels()).toEqual(['Dashboard', 'My projects', 'My profile']);
    expect(await screen.findByText('24 h')).toBeInTheDocument();
  });

  it('blocks employees from admin pages and shows not found for unknown paths', async () => {
    renderApp({ as: USERS.employee, path: '/users' });
    expect(await screen.findByText('You do not have access to this page')).toBeInTheDocument();
  });

  it('shows not found', async () => {
    renderApp({ as: USERS.admin, path: '/nope' });
    expect(await screen.findByText('Page not found')).toBeInTheDocument();
  });
});
