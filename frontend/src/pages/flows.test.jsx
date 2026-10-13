import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { USERS } from '../test/mockApi';
import { renderApp } from '../test/renderApp';
import { addDays, mondayOf, today } from '../utils/format';

const page = (items) => ({ items, total: items.length, page: 1, page_size: 100 });
const project = {
  id: 7, code: 'PRJ-0007', name: 'Apollo', status: 'active', start_date: null, end_date: null,
  manager_id: USERS.manager.id, manager_name: 'Max Manager', budget_cents: 0, planned_cents: 0, consumed_cents: 0,
  consumed_share: null, elapsed_share: null, is_archived: false, at_risk: false, risk_reasons: [],
};
const summary = {
  project,
  deliverables: { total: 0, todo: 0, in_progress: 0, blocked: 0, done: 0, overdue: 0, completion_pct: 0 },
  team: { size: 1, weekly_hours: 20, members: [] },
  budget: { budget_cents: 0, planned_cents: 0, consumed_cents: 0, remaining_cents: 0, consumed_share: null, elapsed_share: null },
  at_risk: false,
  risk_reasons: [],
};

describe('Project requests', () => {
  it('manager submits, edits and withdraws a request', async () => {
    let items = [];
    const sent = [];
    const { user } = renderApp({
      as: USERS.manager,
      path: '/requests',
      routes: {
        'GET /api/project-requests': () => page(items),
        'POST /api/project-requests': ({ body }) => {
          sent.push(body);
          items = [{ id: 5, requested_by: USERS.manager.id, status: 'pending', created_at: today(), ...body }];
          return { status: 201, body: items[0] };
        },
        'PUT /api/project-requests/5': ({ body }) => { sent.push(body); items = [{ ...items[0], ...body }]; return items[0]; },
        'POST /api/project-requests/5/withdraw': () => { items = [{ ...items[0], status: 'withdrawn' }]; return items[0]; },
      },
    });
    await user.click(await screen.findByRole('button', { name: 'Request a project' }));
    let dialog = screen.getByRole('dialog', { name: 'Request a new project' });
    await user.type(within(dialog).getByLabelText(/Project name/), 'Atlas');
    await user.type(within(dialog).getByLabelText(/Proposed budget/), '9000.5');
    await user.click(within(dialog).getByRole('button', { name: 'Submit request' }));
    expect(await screen.findByText('Request submitted. An admin will review it.')).toBeInTheDocument();
    expect(sent[0]).toMatchObject({ name: 'Atlas', proposed_budget_cents: 900050, proposed_start_date: null });
    expect(screen.getByText('$9,000.50')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Edit' }));
    dialog = screen.getByRole('dialog', { name: 'Edit project request' });
    await user.clear(within(dialog).getByLabelText(/Project name/));
    await user.type(within(dialog).getByLabelText(/Project name/), 'Atlas 2');
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Request updated.')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Withdraw' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Withdraw' }));
    expect(await screen.findByText('Withdrawn')).toBeInTheDocument();
  });

  it('admin rejects with a reason and approves', async () => {
    let items = [
      { id: 5, name: 'Zeus', requested_by: 2, requested_by_name: 'Max Manager', proposed_budget_cents: 500000, status: 'pending', created_at: '2026-01-01' },
      { id: 6, name: 'Hera', requested_by: 2, requested_by_name: 'Max Manager', proposed_budget_cents: 0, status: 'pending', created_at: '2026-01-02' },
    ];
    const { user } = renderApp({
      as: USERS.admin,
      path: '/requests',
      routes: {
        'GET /api/project-requests': () => page(items.filter((r) => r.status === 'pending')),
        'POST /api/project-requests/5/reject': ({ body }) => (body.review_note
          ? (items = items.map((r) => (r.id === 5 ? { ...r, status: 'rejected' } : r)), items[0])
          : { status: 400, body: { error: { message: 'Validation failed', details: { review_note: 'is required' } } } }),
        'POST /api/project-requests/6/approve': () => { items = items.map((r) => (r.id === 6 ? { ...r, status: 'approved' } : r)); return {}; },
      },
    });
    const zeus = (await screen.findByText('Zeus')).closest('tr');
    await user.click(within(zeus).getByRole('button', { name: 'Reject' }));
    let dialog = screen.getByRole('dialog', { name: 'Reject request' });
    expect(within(dialog).getByLabelText(/Reason/)).toBeRequired();
    await user.type(within(dialog).getByLabelText(/Reason/), 'No budget');
    await user.click(within(dialog).getByRole('button', { name: 'Reject' }));
    expect(await screen.findByText('Rejected “Zeus”.')).toBeInTheDocument();

    await user.click(within(screen.getByText('Hera').closest('tr')).getByRole('button', { name: 'Approve' }));
    dialog = screen.getByRole('dialog', { name: 'Approve request' });
    await user.click(within(dialog).getByRole('button', { name: 'Approve and create project' }));
    expect(await screen.findByText('No pending requests')).toBeInTheDocument();
  });
});

describe('Resources tab', () => {
  it('lists bookings with cost, edits hours, ends and restores a booking', async () => {
    let row = { id: 50, project_id: 7, user_id: 3, full_name: 'Eve Employee', employee_id: 'EMP0002', job_title: 'Engineer',
      project_role: 'Dev', hours_per_week: 20, start_date: '2026-01-05', end_date: '2026-02-01', planned_cents: 400000, is_archived: false };
    const updates = [];
    const { user } = renderApp({
      as: USERS.manager,
      path: '/projects/7?tab=resources',
      routes: {
        'GET /api/projects/7/summary': summary,
        'GET /api/assignments': ({ url }) => {
          const archived = new URL(url, 'http://x').searchParams.get('archived');
          return page(archived === 'false' && row.is_archived ? [] : [row]);
        },
        'GET /api/users/3/workload': { weeks: [], assignments: [] },
        'PUT /api/assignments/50': ({ body }) => { updates.push(body); row = { ...row, ...body }; return row; },
        'POST /api/assignments/50/archive': () => { row = { ...row, is_archived: true }; return row; },
        'POST /api/assignments/50/reactivate': () => { row = { ...row, is_archived: false }; return row; },
      },
    });
    expect(await screen.findByText('$4,000')).toBeInTheDocument();
    expect(screen.getByText('Jan 5, 2026 – Feb 1, 2026')).toBeInTheDocument();

    await user.click(within(screen.getByRole('table')).getByRole('button', { name: 'Edit' }));
    const dialog = screen.getByRole('dialog');
    await user.clear(within(dialog).getByLabelText(/Hours per week/));
    await user.type(within(dialog).getByLabelText(/Hours per week/), '25');
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(updates[0]).toMatchObject({ hours_per_week: 25, start_date: '2026-01-05' }));

    await user.click(await screen.findByRole('button', { name: 'End booking' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'End booking' }));
    expect(await screen.findByText('Nobody is booked yet')).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Show bookings'), 'all');
    await user.click(await screen.findByRole('button', { name: 'Restore' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Restore' }));
    await waitFor(() => expect(row.is_archived).toBe(false));
  });

  it('employees see the team without cost or actions', async () => {
    renderApp({
      as: USERS.employee,
      path: '/projects/7?tab=resources',
      routes: {
        'GET /api/projects/7/summary': summary,
        'GET /api/assignments': page([{ id: 50, full_name: 'Eve Employee', employee_id: 'EMP0002', hours_per_week: 20,
          start_date: '2026-01-05', end_date: '2026-02-01', is_archived: false }]),
      },
    });
    expect(await screen.findByText('Eve Employee')).toBeInTheDocument();
    expect(screen.queryByText('Planned cost')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Book someone' })).not.toBeInTheDocument();
  });
});

describe('Timesheet editing', () => {
  it('edits and withdraws a pending entry, and moves between weeks', async () => {
    const start = mondayOf(today());
    let entries = [{ id: 1, project_id: 7, project_name: 'Apollo', work_date: start, hours: 4, note: 'Spec', status: 'pending' },
      { id: 2, project_id: 7, project_name: 'Apollo', work_date: start, hours: 2, status: 'rejected', review_note: 'Wrong day' }];
    const weeks = [];
    const sent = [];
    const { user } = renderApp({
      as: USERS.employee,
      path: '/timesheet',
      routes: {
        'GET /api/timesheets/week': ({ url }) => {
          const s = new URL(url, 'http://x').searchParams.get('start');
          weeks.push(s);
          return {
            week_start: s, week_end: addDays(s, 6), booked_hours: 20, logged_hours: 4, approved_hours: 0,
            days: Array.from({ length: 7 }, (_, i) => ({ date: addDays(s, i), hours: i === 0 ? 4 : 0 })),
            bookings: [{ project_id: 7, project_name: 'Apollo', hours_per_week: 20 }],
            entries,
          };
        },
        'PUT /api/timesheets/1': ({ body }) => { sent.push(body); entries = [{ ...entries[0], ...body }, entries[1]]; return entries[0]; },
        'POST /api/timesheets/1/withdraw': () => { entries = [{ ...entries[0], status: 'withdrawn' }, entries[1]]; return entries[0]; },
      },
    });
    expect(await screen.findByText('“Wrong day”')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Edit' }));
    const form = screen.getByRole('form', { name: 'Edit hours' });
    await user.clear(within(form).getByLabelText(/Hours/));
    await user.type(within(form).getByLabelText(/Hours/), '5.5');
    await user.click(within(form).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(sent[0]).toMatchObject({ hours: 5.5, note: 'Spec' }));

    await user.click(await screen.findByRole('button', { name: 'Withdraw' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Withdraw' }));
    expect(await screen.findByText('Withdrawn')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Previous week' }));
    await waitFor(() => expect(weeks.at(-1)).toBe(addDays(start, -7)));
    expect(screen.getByRole('button', { name: 'Next week' })).toBeEnabled();
  });
});

describe('People admin actions', () => {
  it('resets a password, shows it once and copies the sign-in details', async () => {
    const { user } = renderApp({
      as: USERS.admin,
      path: '/users',
      routes: {
        'GET /api/users': page([{ ...USERS.employee, is_active: true, current_week_hours: 40 }]),
        'POST /api/users/3/reset-password': { employee_id: 'EMP0002', email: 'eve@x.com', temporary_password: 'Zz9yX8' },
      },
    });
    expect(await screen.findByRole('meter', { name: '40 of 40 hours allocated' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Reset password' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Reset password' }));
    const creds = await screen.findByRole('dialog', { name: 'Password reset' });
    expect(within(creds).getByText('Zz9yX8')).toBeInTheDocument();
    await user.click(within(creds).getByRole('button', { name: 'Copy' }));
    expect(await within(creds).findByRole('button', { name: 'Copied' })).toBeInTheDocument();
    expect(await navigator.clipboard.readText()).toBe('Email: eve@x.com\nPassword: Zz9yX8');
  });

  it('admin edits another user and deactivates them', async () => {
    let sent;
    const other = { ...USERS.employee, is_active: true, current_week_hours: 0 };
    const { user } = renderApp({
      as: USERS.admin,
      path: '/users',
      routes: {
        'GET /api/users': page([other, { ...USERS.manager, is_active: true, current_week_hours: 0 }]),
        'PUT /api/users/3': ({ body }) => { sent = body; return { ...other, ...body }; },
      },
    });
    const row = (await screen.findByText('Eve Employee')).closest('tr');
    await user.click(within(row).getByRole('button', { name: 'Edit' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('checkbox', { name: /Active/ }));
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(sent).toMatchObject({ is_active: false, salary_cents: 8000000, role: 'employee' }));
  });
});

describe('Layout', () => {
  it('opens and closes the mobile menu', async () => {
    const { user } = renderApp({
      as: USERS.employee,
      path: '/profile',
      routes: { 'GET /api/users/3/workload': { current_week_hours: 0, weeks: [], assignments: [] } },
    });
    const toggle = await screen.findByRole('button', { name: 'Open menu' });
    await user.click(toggle);
    expect(screen.getByRole('button', { name: 'Close menu' })).toHaveAttribute('aria-expanded', 'true');
    await user.click(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: 'My profile' }));
    expect(screen.getByRole('button', { name: 'Open menu' })).toHaveAttribute('aria-expanded', 'false');
  });

  it('allocation grid moves between weeks and searches people', async () => {
    const queries = [];
    const { user } = renderApp({
      as: USERS.admin,
      path: '/allocation',
      routes: {
        'GET /api/assignments/grid': ({ url }) => {
          queries.push(Object.fromEntries(new URL(url, 'http://x').searchParams));
          return { weeks: [], rows: [], max_hours: 40, over_allocated_people: 0, total: 0, page: 1, page_size: 50 };
        },
      },
    });
    expect(await screen.findByText('Nobody matches')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Next 4 weeks' }));
    await waitFor(() => expect(queries.at(-1).from).toBe(addDays(mondayOf(today()), 28)));
    await user.click(screen.getByRole('checkbox', { name: /Only people with bookings/ }));
    await user.type(screen.getByLabelText('Search people'), 'eve');
    await waitFor(() => expect(queries.at(-1)).toMatchObject({ q: 'eve', only_over: 'true' }));
  });
});
