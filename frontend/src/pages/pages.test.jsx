import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { USERS } from '../test/mockApi';
import { renderApp } from '../test/renderApp';

const project = {
  id: 7, code: 'PRJ-0007', name: 'Apollo', description: 'Moon', status: 'active', health: 'amber',
  start_date: '2026-01-01', end_date: '2026-12-31', manager_id: USERS.manager.id, manager_name: 'Max Manager',
  budget_total: 1000, is_archived: false,
};

function summary(overrides = {}) {
  return {
    project: { ...project, ...overrides },
    deliverables: { total: 2, todo: 1, in_progress: 0, blocked: 0, done: 1, overdue: 1, avg_progress: 50, completion_pct: 50 },
    team: {
      size: 1,
      total_hours: 30,
      members: [{ id: 50, user_id: 3, employee_id: 'EMP0002', full_name: 'Eve Employee', job_title: 'Engineer', project_role: 'Dev', hours_per_week: 30 }],
    },
    budget: { planned: 800, actual: 300, budget_total: 1000, remaining: 700, burn_pct: 30 },
  };
}

describe('ProfilePage', () => {
  it('lets an employee edit only first name, last name and email', async () => {
    let sent;
    const { user } = renderApp({
      as: USERS.employee,
      path: '/profile',
      routes: {
        'GET /api/users/3/workload': { allocated_hours: 30, remaining_hours: 10, max_hours: 40, assignments: [] },
        'PUT /api/users/me': ({ body }) => { sent = body; return { ...USERS.employee, ...body, full_name: `${body.first_name} ${body.last_name}` }; },
      },
    });

    const form = (await screen.findByRole('heading', { name: 'Edit personal information' })).closest('section');
    const inputs = within(form).getAllByRole('textbox');
    expect(inputs.map((i) => i.name)).toEqual(['first_name', 'last_name', 'email']);
    // read-only details are shown but not editable
    expect(screen.getByText('EMP0002')).toBeInTheDocument();
    expect(screen.getByText('$80,000')).toBeInTheDocument();

    await user.clear(within(form).getByLabelText(/First name/));
    await user.type(within(form).getByLabelText(/First name/), 'Evelyn');
    await user.click(within(form).getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByText('Your details have been saved.')).toBeInTheDocument();
    expect(sent).toEqual({ first_name: 'Evelyn', last_name: 'Employee', email: 'eve@x.com' });
    expect(screen.getByRole('heading', { name: 'Evelyn Employee' })).toBeInTheDocument();
  });

  it('shows API validation errors next to the field', async () => {
    const { user } = renderApp({
      as: USERS.employee,
      path: '/profile',
      routes: {
        'GET /api/users/3/workload': { allocated_hours: 0, remaining_hours: 40, max_hours: 40, assignments: [] },
        'PUT /api/users/me': { status: 400, body: { error: { message: 'Validation failed', details: { email: 'must be a valid email address' } } } },
      },
    });
    await user.click(await screen.findByRole('button', { name: 'Save changes' }));
    expect(await screen.findByText('Must be a valid email address')).toBeInTheDocument();
  });
});

describe('ProjectDetailPage', () => {
  it('employee sees a read-only project without budget', async () => {
    const data = summary();
    delete data.budget;
    renderApp({ as: USERS.employee, path: '/projects/7', routes: { 'GET /api/projects/7/summary': data } });
    expect(await screen.findByRole('heading', { name: 'Apollo' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Archive' })).not.toBeInTheDocument();
    const tabs = screen.getAllByRole('tab').map((t) => t.textContent);
    expect(tabs).toEqual(['Overview', 'Team (1)', 'Deliverables (2)']);
  });

  it('manager can edit their project but not archive it', async () => {
    renderApp({ as: USERS.manager, path: '/projects/7', routes: { 'GET /api/projects/7/summary': summary() } });
    expect(await screen.findByRole('button', { name: 'Edit' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Archive' })).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Budget' })).toBeInTheDocument();
  });

  it('admin archives after confirming', async () => {
    let archived = false;
    const { user } = renderApp({
      as: USERS.admin,
      path: '/projects/7',
      routes: {
        'GET /api/projects/7/summary': () => summary({ is_archived: archived }),
        'POST /api/projects/7/archive': () => { archived = true; return { ...project, is_archived: true }; },
      },
    });
    await user.click(await screen.findByRole('button', { name: 'Archive' }));
    const dialog = screen.getByRole('dialog', { name: 'Archive project?' });
    await user.click(within(dialog).getByRole('button', { name: 'Archive' }));
    expect(await screen.findByRole('button', { name: 'Reactivate' })).toBeInTheDocument();
    expect(screen.getByText(/This project is archived and read-only/)).toBeInTheDocument();
  });

  it('shows the capacity error when reactivation would exceed 40 hours', async () => {
    const { user } = renderApp({
      as: USERS.admin,
      path: '/projects/7',
      routes: {
        'GET /api/projects/7/summary': summary({ is_archived: true }),
        'POST /api/projects/7/reactivate': {
          status: 409,
          body: { error: { message: 'Reactivating would exceed the weekly hour limit', details: { over_allocated: [{ user_id: 3 }] } } },
        },
      },
    });
    await user.click(await screen.findByRole('button', { name: 'Reactivate' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Reactivate' }));
    expect(await screen.findByText(/exceed the weekly hour limit \(1 person affected\)/)).toBeInTheDocument();
  });

  it('warns and blocks assigning more hours than a person has left', async () => {
    const { user } = renderApp({
      as: USERS.manager,
      path: '/projects/7?tab=team',
      routes: {
        'GET /api/projects/7/summary': summary({ }),
        'GET /api/users': { items: [{ ...USERS.employee, id: 4, full_name: 'Sam Report', allocated_hours: 32 }], total: 1, page: 1, page_size: 100 },
        'GET /api/users/4/workload': { allocated_hours: 32, remaining_hours: 8, max_hours: 40, assignments: [] },
      },
    });
    await user.click(await screen.findByRole('button', { name: 'Assign person' }));
    const dialog = screen.getByRole('dialog');
    await waitFor(() => expect(within(dialog).getByRole('option', { name: /Sam Report/ })).toBeInTheDocument());
    await user.selectOptions(within(dialog).getByLabelText(/Person/), '4');
    await user.clear(within(dialog).getByLabelText(/Hours per week/));
    await user.type(within(dialog).getByLabelText(/Hours per week/), '10');
    expect(await within(dialog).findByText(/8 h available for this project — reduce the hours/)).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Assign' })).toBeDisabled();
  });
});

describe('UsersPage', () => {
  it('admin creates a user and sees the generated credentials once', async () => {
    const { user } = renderApp({
      as: USERS.admin,
      path: '/users',
      routes: {
        'GET /api/users': { items: [], total: 0, page: 1, page_size: 20 },
        'POST /api/users': ({ body }) => ({
          status: 201,
          body: { user: { ...body, id: 9, full_name: `${body.first_name} ${body.last_name}` }, employee_id: 'EMP0042', temporary_password: 'aB3dE9' },
        }),
      },
    });
    await user.click(await screen.findByRole('button', { name: 'New user' }));
    const dialog = screen.getByRole('dialog', { name: 'New user' });
    await user.type(within(dialog).getByLabelText(/First name/), 'Nia');
    await user.type(within(dialog).getByLabelText(/Last name/), 'New');
    await user.type(within(dialog).getByLabelText(/Email/), 'nia@x.com');
    await user.type(within(dialog).getByLabelText(/Job title/), 'Analyst');
    await user.click(within(dialog).getByRole('button', { name: 'Create user' }));

    const creds = await screen.findByRole('dialog', { name: 'User created' });
    expect(within(creds).getByText('EMP0042')).toBeInTheDocument();
    expect(within(creds).getByText('aB3dE9')).toBeInTheDocument();
    await user.click(within(creds).getByRole('button', { name: 'Done' }));
    expect(screen.queryByText('aB3dE9')).not.toBeInTheDocument();
  });

  it('manager sees a read-only team list', async () => {
    renderApp({
      as: USERS.manager,
      path: '/users',
      routes: {
        'GET /api/users': { items: [{ ...USERS.employee, allocated_hours: 40 }], total: 1, page: 1, page_size: 20 },
      },
    });
    expect(await screen.findByRole('heading', { name: 'My team' })).toBeInTheDocument();
    expect(await screen.findByText('Eve Employee')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'New user' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    expect(screen.getByRole('meter', { name: '40 of 40 hours allocated' })).toBeInTheDocument();
  });
});

describe('ProjectsPage', () => {
  it('lists projects and sends search and filters to the API', async () => {
    const queries = [];
    const { user } = renderApp({
      as: USERS.admin,
      path: '/projects',
      routes: {
        'GET /api/projects': ({ url }) => {
          queries.push(Object.fromEntries(new URL(url, 'http://x').searchParams));
          return { items: [{ ...project, team_size: 1, team_hours: 30, deliverable_count: 4, deliverables_done: 1 }], total: 1, page: 1, page_size: 20 };
        },
      },
    });
    expect(await screen.findByRole('link', { name: 'Apollo' })).toBeInTheDocument();
    expect(screen.getByText('25%')).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Filter by health'), 'red');
    await user.type(screen.getByLabelText('Search projects'), 'apo');
    await waitFor(() => expect(queries.at(-1)).toMatchObject({ q: 'apo', health: 'red', archived: 'false' }));
    await user.click(screen.getByRole('button', { name: /Due/ }));
    await waitFor(() => expect(queries.at(-1).sort).toBe('end_date'));
  });

  it('manager is offered a project request instead of creation', async () => {
    renderApp({
      as: USERS.manager,
      path: '/projects',
      routes: { 'GET /api/projects': { items: [], total: 0, page: 1, page_size: 20 } },
    });
    expect(await screen.findByRole('button', { name: 'Request a project' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'New project' })).not.toBeInTheDocument();
    expect(await screen.findByText('No projects yet')).toBeInTheDocument();
  });
});

describe('RequestsPage', () => {
  it('admin approves a pending request', async () => {
    let status = 'pending';
    const { user } = renderApp({
      as: USERS.admin,
      path: '/requests',
      routes: {
        'GET /api/project-requests': () => ({
          items: status === 'pending' ? [{ id: 5, name: 'Zeus', requested_by: 2, requested_by_name: 'Max Manager', proposed_budget: 5000, status, created_at: '2026-01-01' }] : [],
          total: status === 'pending' ? 1 : 0, page: 1, page_size: 20,
        }),
        'POST /api/project-requests/5/approve': () => { status = 'approved'; return { request: {}, project: {} }; },
      },
    });
    await user.click(await screen.findByRole('button', { name: 'Approve' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Approve and create project' }));
    expect(await screen.findByText(/Approved “Zeus”/)).toBeInTheDocument();
    expect(await screen.findByText('No pending requests')).toBeInTheDocument();
  });
});
