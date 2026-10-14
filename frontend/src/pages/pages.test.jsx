import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { USERS } from '../test/mockApi';
import { renderApp } from '../test/renderApp';
import { addDays, mondayOf, today } from '../utils/format';

const project = {
  id: 7, code: 'PRJ-0007', name: 'Apollo', description: 'Moon', status: 'active', start_date: '2026-01-01',
  end_date: '2026-12-31', manager_id: USERS.manager.id, manager_name: 'Max Manager', budget_cents: 100000,
  planned_cents: 80000, consumed_cents: 30000, consumed_share: 0.3, elapsed_share: 0.5, over_burn: false,
  is_archived: false, at_risk: true, risk_reasons: ['1 overdue deliverable'], deliverable_count: 2, deliverables_done: 1,
};
const summary = (overrides = {}) => ({
  project: { ...project, ...overrides },
  deliverables: { total: 2, todo: 1, in_progress: 0, blocked: 0, done: 1, overdue: 1, completion_pct: 50 },
  team: { size: 1, weekly_hours: 30, members: [{ id: 50, user_id: 3, full_name: 'Eve Employee', start_date: '2026-01-01', end_date: '2026-12-31', hours_per_week: 30 }] },
  budget: { budget_cents: 100000, planned_cents: 80000, consumed_cents: 30000, remaining_cents: 70000, consumed_share: 0.3, elapsed_share: 0.5 },
  at_risk: !overrides.is_archived,
  risk_reasons: ['1 overdue deliverable'],
});
const page = (items) => ({ items, total: items.length, page: 1, page_size: 100 });

describe('Projects list', () => {
  it('shows status, risk and budget use, and filters on the server', async () => {
    const queries = [];
    const { user } = renderApp({
      as: USERS.admin,
      path: '/projects?at_risk=true',
      routes: {
        'GET /api/projects': ({ url }) => {
          queries.push(Object.fromEntries(new URL(url, 'http://x').searchParams));
          return page([project]);
        },
      },
    });
    expect(await screen.findByRole('link', { name: 'Apollo' })).toBeInTheDocument();
    expect(queries[0]).toMatchObject({ at_risk: 'true', archived: 'false' });
    expect(within(screen.getByRole('table')).getByText('At risk')).toBeInTheDocument();
    expect(screen.getByText('30% of $1,000')).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Filter by status'), 'on_hold');
    await user.type(screen.getByLabelText('Search projects'), 'apo');
    await waitFor(() => expect(queries.at(-1)).toMatchObject({ q: 'apo', status: 'on_hold' }));
  });
});

describe('Project detail', () => {
  it('shows the risk reasons and lets a manager edit only description and status', async () => {
    let sent;
    const { user } = renderApp({
      as: USERS.manager,
      path: '/projects/7',
      routes: {
        'GET /api/projects/7/summary': summary(),
        'PUT /api/projects/7': ({ body }) => { sent = body; return project; },
      },
    });
    expect(await screen.findByText('1 overdue deliverable')).toBeInTheDocument();
    expect(screen.getAllByRole('tab').map((t) => t.textContent))
      .toEqual(['Overview', 'Deliverables (2)', 'Dependencies', 'Resources', 'Budget']);
    expect(screen.queryByRole('button', { name: 'Archive' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Edit' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).queryByLabelText(/Name/)).not.toBeInTheDocument();
    expect(within(dialog).queryByLabelText(/Budget/)).not.toBeInTheDocument();
    await user.selectOptions(within(dialog).getByLabelText(/Status/), 'on_hold');
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(sent).toEqual({ description: 'Moon', status: 'on_hold' }));
  });

  it('admin archives after confirming', async () => {
    let archived = false;
    const { user } = renderApp({
      as: USERS.admin,
      path: '/projects/7',
      routes: {
        'GET /api/projects/7/summary': () => summary({ is_archived: archived }),
        'POST /api/projects/7/archive': () => { archived = true; return project; },
      },
    });
    await user.click(await screen.findByRole('button', { name: 'Archive' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Archive' }));
    expect(await screen.findByRole('button', { name: 'Reactivate' })).toBeInTheDocument();
    expect(screen.getByText(/archived and read-only/)).toBeInTheDocument();
  });

  it('booking over 40 hours shows the weekly clash and the server refusal naming the projects', async () => {
    const week = mondayOf(today());
    const { user } = renderApp({
      as: USERS.manager,
      path: '/projects/7?tab=resources',
      routes: {
        'GET /api/projects/7/summary': summary({ start_date: null, end_date: null }),
        'GET /api/assignments': page([]),
        'GET /api/users': page([{ ...USERS.employee, id: 4, full_name: 'Sam Report', current_week_hours: 32 }]),
        'GET /api/users/4/workload': { weeks: [{ week_start: week, hours: 32, projects: [] }], assignments: [] },
        'POST /api/assignments': {
          status: 409,
          body: { error: { message: `Booking exceeds 40 hours in the week of ${week} (42 h booked across PRJ-0002 Gemini, PRJ-0007 Apollo)` } },
        },
      },
    });
    await user.click(await screen.findByRole('button', { name: 'Book someone' }));
    const dialog = screen.getByRole('dialog');
    await waitFor(() => expect(within(dialog).getByRole('option', { name: /Sam Report/ })).toBeInTheDocument());
    await user.selectOptions(within(dialog).getByLabelText(/Person/), '4');
    await user.clear(within(dialog).getByLabelText(/Hours per week/));
    await user.type(within(dialog).getByLabelText(/Hours per week/), '10');
    expect(await within(dialog).findByText(/over 40 hours — this booking will be refused/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Book' }));
    expect(await within(dialog).findByText(/PRJ-0002 Gemini, PRJ-0007 Apollo/)).toBeInTheDocument();
  });

  it('deliverables: dependencies, refusal to finish early, timeline and archive', async () => {
    const items = [
      { id: 1, title: 'Design', status: 'todo', depends_on: [], is_blocked: false, progress_pct: 0, start_date: '2026-02-01', due_date: '2026-02-10', is_archived: false },
      { id: 2, title: 'Build', status: 'todo', depends_on: [1], is_blocked: true, progress_pct: 0, start_date: '2026-02-11', due_date: '2026-03-01', is_archived: false },
    ];
    let archivedId = null;
    const { user } = renderApp({
      as: USERS.manager,
      path: '/projects/7?tab=deliverables',
      routes: {
        'GET /api/projects/7/summary': summary(),
        'GET /api/deliverables': () => page(items.filter((d) => d.id !== archivedId)),
        'PUT /api/deliverables/2': { status: 409, body: { error: { message: "Can't mark this done while it depends on unfinished work: Design (todo)" } } },
        'POST /api/deliverables/1/archive': () => { archivedId = 1; return items[0]; },
      },
    });
    expect(await screen.findByText('Depends on: Design')).toBeInTheDocument();
    expect(screen.getByText('Waiting')).toBeInTheDocument();

    const row = screen.getByText('Build').closest('tr');
    await user.click(within(row).getByRole('button', { name: 'Edit' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByRole('checkbox', { name: /Design/ })).toBeChecked();
    await user.selectOptions(within(dialog).getByLabelText(/Status/), 'done');
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));
    expect(await within(dialog).findByText(/depends on unfinished work: Design/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    await user.click(screen.getByRole('button', { name: 'Timeline' }));
    expect(screen.getByRole('list', { name: 'Deliverable timeline' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'List' }));

    const designRow = screen.getAllByText('Design').map((el) => el.closest('tr')).find(Boolean);
    await user.click(within(designRow).getByRole('button', { name: 'Archive' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Archive' }));
    await waitFor(() => expect(screen.queryAllByText('Design').filter((el) => el.closest('tbody'))).toHaveLength(0));
  });

  it('milestones: single date in the form, diamond on the list and timeline, type filter', async () => {
    const items = [
      { id: 1, title: 'Build', status: 'in_progress', depends_on: [], is_blocked: false, progress_pct: 50, start_date: '2026-02-01', due_date: '2026-03-01', is_archived: false, is_milestone: false },
      { id: 2, title: 'Go-live', status: 'todo', depends_on: [1], is_blocked: true, progress_pct: 0, start_date: null, due_date: '2026-01-15', is_archived: false, is_milestone: true, is_overdue: true },
    ];
    let sent = null;
    const queries = [];
    const { user } = renderApp({
      as: USERS.manager,
      path: '/projects/7?tab=deliverables',
      routes: {
        'GET /api/projects/7/summary': summary(),
        'GET /api/deliverables': ({ url }) => { queries.push(url); return page(items); },
        'POST /api/deliverables': ({ body }) => { sent = body; return { status: 201, body: { ...body, id: 3 } }; },
      },
    });
    const goLive = (await screen.findAllByText('Go-live')).find((el) => el.closest('tbody')).closest('tr');
    expect(within(goLive).getByRole('img', { name: 'Milestone' })).toBeInTheDocument();
    expect(within(goLive).getByText(/missed/)).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Filter by type'), 'true');
    await waitFor(() => expect(queries.at(-1)).toContain('milestone=true'));

    await user.click(screen.getByRole('button', { name: 'Timeline' }));
    const timeline = screen.getByRole('list', { name: 'Deliverable timeline' });
    expect(timeline.querySelector('.timeline-milestone')).toHaveAttribute('title', expect.stringContaining('milestone on'));

    await user.click(screen.getByRole('button', { name: 'New deliverable' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByLabelText('Start date')).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText(/Title/), 'Beta');
    await user.click(within(dialog).getByRole('checkbox', { name: /Milestone/ }));
    expect(within(dialog).queryByLabelText('Start date')).not.toBeInTheDocument();
    await user.type(within(dialog).getByLabelText(/Milestone date/), '2026-04-01');
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(sent).toMatchObject({ title: 'Beta', is_milestone: true, start_date: null, due_date: '2026-04-01' }));
  });

  it('dependency view orders deliverables by what they wait on', async () => {
    renderApp({
      as: USERS.employee,
      path: '/projects/7?tab=dependencies',
      routes: {
        'GET /api/projects/7/summary': summary(),
        'GET /api/deliverables/graph': {
          nodes: [
            { id: 1, title: 'Design', status: 'done', depends_on: [], level: 0, is_blocked: false },
            { id: 2, title: 'Build', status: 'todo', depends_on: [1], level: 1, is_blocked: false },
            { id: 3, title: 'Launch', status: 'todo', depends_on: [2], level: 2, is_blocked: true },
          ],
          edges: [{ from: 1, to: 2 }, { from: 2, to: 3 }],
        },
      },
    });
    const columns = await screen.findAllByRole('heading', { level: 3 });
    expect(columns.map((h) => h.textContent)).toEqual(['Can start now', 'Step 2', 'Step 3']);
    expect(screen.getByText('unblocks Build')).toBeInTheDocument();
    expect(screen.getByText('Waiting on unfinished work')).toBeInTheDocument();
  });

  it('budget tab shows planned vs consumed and per-person cost, and sets the budget in cents', async () => {
    let sent;
    const { user } = renderApp({
      as: USERS.manager,
      path: '/projects/7?tab=budget',
      routes: {
        'GET /api/projects/7/summary': summary(),
        'GET /api/budgets/7': {
          ...project, remaining_cents: 70000, unplanned_cents: 20000,
          people: [{ user_id: 3, full_name: 'Eve Employee', job_title: 'Engineer', planned_cents: 80000, planned_hours: 16, consumed_cents: 30000, approved_hours: 6 }],
          by_month: [{ month: '2026-02-01', consumed_cents: 30000, hours: 6 }],
        },
        'PUT /api/budgets/7': ({ body }) => { sent = body; return project; },
      },
    });
    expect(await screen.findByText('$700')).toBeInTheDocument();
    expect(screen.getByText('6 h · $300')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Change budget' }));
    const input = within(screen.getByRole('dialog')).getByLabelText(/Budget/);
    await user.clear(input);
    await user.type(input, '1234.56');
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(sent).toEqual({ budget_cents: 123456 }));
  });
});

describe('Allocation grid', () => {
  it('shows people down, weeks across, and flags full and over-booked weeks', async () => {
    const week = mondayOf(today());
    renderApp({
      as: USERS.manager,
      path: '/allocation',
      routes: {
        'GET /api/assignments/grid': {
          weeks: [week, addDays(week, 7)],
          max_hours: 40,
          over_allocated_people: 1,
          rows: [{
            id: 3, full_name: 'Eve Employee', job_title: 'Engineer', peak_hours: 44,
            cells: [
              { week_start: week, hours: 40, full: true, over: false, projects: [{ code: 'PRJ-0007', name: 'Apollo', hours: 40 }] },
              { week_start: addDays(week, 7), hours: 44, full: true, over: true, projects: [] },
            ],
          }],
          total: 1, page: 1, page_size: 50,
        },
      },
    });
    const table = await screen.findByRole('table');
    const cells = within(table).getAllByRole('cell');
    expect(cells[0]).toHaveClass('full');
    expect(cells[0]).toHaveAttribute('title', 'PRJ-0007 Apollo: 40 h');
    expect(cells[1]).toHaveClass('over');
    expect(screen.getByText('1 over-allocated')).toBeInTheDocument();
  });
});

describe('Timesheets and approvals', () => {
  it('employee logs hours on a booked project', async () => {
    const start = mondayOf(today());
    let sent;
    const days = Array.from({ length: 7 }, (_, i) => ({ date: addDays(start, i), hours: 0 }));
    const { user } = renderApp({
      as: USERS.employee,
      path: '/timesheet',
      routes: {
        'GET /api/timesheets/week': {
          week_start: start, week_end: addDays(start, 6), days, booked_hours: 30, logged_hours: 0, approved_hours: 0,
          bookings: [{ project_id: 7, project_name: 'Apollo', hours_per_week: 30 }], entries: [],
        },
        'POST /api/timesheets': ({ body }) => { sent = body; return { status: 201, body: { id: 1, ...body } }; },
      },
    });
    expect(await screen.findByText('30 h')).toBeInTheDocument();
    const form = screen.getByRole('form', { name: 'Log hours' });
    await user.clear(within(form).getByLabelText(/Hours/));
    await user.type(within(form).getByLabelText(/Hours/), '7.5');
    await user.click(within(form).getByRole('button', { name: 'Log hours' }));
    await waitFor(() => expect(sent).toMatchObject({ project_id: 7, hours: 7.5, work_date: today() }));
  });

  it('manager approves and rejects direct reports\' hours', async () => {
    const entries = [
      { id: 1, user_id: 3, user_manager_id: USERS.manager.id, full_name: 'Eve Employee', work_date: today(), project_name: 'Apollo', hours: 8, status: 'pending' },
      { id: 2, user_id: 3, user_manager_id: USERS.manager.id, full_name: 'Eve Employee', work_date: today(), project_name: 'Apollo', hours: 2, status: 'pending' },
    ];
    let pending = [...entries];
    let rejectNote;
    const { user } = renderApp({
      as: USERS.manager,
      path: '/approvals',
      routes: {
        'GET /api/timesheets': () => ({ ...page(pending), total_hours: pending.reduce((s, e) => s + e.hours, 0) }),
        'POST /api/timesheets/1/approve': () => { pending = pending.filter((e) => e.id !== 1); return entries[0]; },
        'POST /api/timesheets/2/reject': ({ body }) => { rejectNote = body.review_note; pending = []; return entries[1]; },
      },
    });
    expect(await screen.findByText('Total: 10 h')).toBeInTheDocument();
    const first = screen.getByText('8 h').closest('tr');
    await user.click(within(first).getByRole('button', { name: 'Approve' }));
    expect(await screen.findByText('Approved 1 entry.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Reject' }));
    await user.type(within(screen.getByRole('dialog')).getByLabelText(/Reason/), 'Wrong day');
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Reject' }));
    expect(await screen.findByText('Nothing waiting for approval')).toBeInTheDocument();
    expect(rejectNote).toBe('Wrong day');
  });
});

describe('Notifications and audit', () => {
  it('lists notifications and marks them read', async () => {
    let read = false;
    const { user } = renderApp({
      as: USERS.manager,
      path: '/notifications',
      routes: {
        'GET /api/activity/notifications': () => ({
          ...page([{ id: 9, message: 'Eve Employee logged 8 h on PRJ-0007', entity: 'time_entry', entity_id: 1, created_at: new Date().toISOString(), read_at: read ? 'x' : null }]),
          unread: read ? 0 : 1,
        }),
        'POST /api/activity/notifications/read-all': () => { read = true; return { unread: 0 }; },
      },
    });
    expect(await screen.findByText('Eve Employee logged 8 h on PRJ-0007')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Mark all as read' }));
    await waitFor(() => expect(screen.queryByLabelText('Unread')).not.toBeInTheDocument());
  });

  it('admin filters the audit log', async () => {
    const queries = [];
    const { user } = renderApp({
      as: USERS.admin,
      path: '/audit',
      routes: {
        'GET /api/activity/audit': ({ url }) => {
          queries.push(Object.fromEntries(new URL(url, 'http://x').searchParams));
          return page([{ id: 1, created_at: '2026-10-13T10:00:00Z', actor_name: 'Ada Admin', actor_role: 'admin', action: 'archive', entity: 'project', entity_id: 7, summary: 'archived project PRJ-0007 Apollo' }]);
        },
      },
    });
    expect(await screen.findByText('archived project PRJ-0007 Apollo')).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Filter by record type'), 'project');
    await waitFor(() => expect(queries.at(-1)).toMatchObject({ entity: 'project' }));
  });
});

describe('People', () => {
  it('admin creates a user and sees the sign-in email and generated password once', async () => {
    let sent;
    const { user } = renderApp({
      as: USERS.admin,
      path: '/users',
      routes: {
        'GET /api/users': page([]),
        'POST /api/users': ({ body }) => {
          sent = body;
          return { status: 201, body: { user: { ...body, id: 9, full_name: 'Nia New' }, employee_id: 'EMP0042', temporary_password: 'aB3dE9' } };
        },
      },
    });
    await user.click(await screen.findByRole('button', { name: 'New user' }));
    const dialog = screen.getByRole('dialog', { name: 'New user' });
    await user.type(within(dialog).getByLabelText(/First name/), 'Nia');
    await user.type(within(dialog).getByLabelText(/Last name/), 'New');
    expect(within(dialog).getByText('Use the full name or initials: nia.new@… or nn@…')).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText(/Email/), 'nia.new@x.com');
    await user.type(within(dialog).getByLabelText(/Job title/), 'Analyst');
    await user.type(within(dialog).getByLabelText(/salary/), '104000');
    await user.click(within(dialog).getByRole('button', { name: 'Create user' }));
    const creds = await screen.findByRole('dialog', { name: 'User created' });
    expect(within(creds).getByText('nia.new@x.com')).toBeInTheDocument();
    expect(within(creds).getByText('aB3dE9')).toBeInTheDocument();
    expect(sent.salary_cents).toBe(10400000);
  });

  it('admin cannot change their own role or salary', async () => {
    const { user } = renderApp({
      as: USERS.admin,
      path: '/users',
      routes: { 'GET /api/users': page([{ ...USERS.admin, is_active: true, current_week_hours: 0 }]) },
    });
    await user.click(await screen.findByRole('button', { name: 'Edit' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByLabelText(/Role/)).toBeDisabled();
    expect(within(dialog).getByLabelText(/salary/)).toBeDisabled();
  });

  it('employee edits only name and email on their profile', async () => {
    let sent;
    const { user } = renderApp({
      as: USERS.employee,
      path: '/profile',
      routes: {
        'GET /api/users/3/workload': { current_week_hours: 30, weeks: [], assignments: [] },
        'PUT /api/users/me': ({ body }) => { sent = body; return { ...USERS.employee, ...body }; },
      },
    });
    const form = (await screen.findByRole('heading', { name: 'Edit personal information' })).closest('section');
    expect(within(form).getAllByRole('textbox').map((i) => i.name)).toEqual(['first_name', 'last_name', 'email']);
    expect(screen.getByText('$80,000')).toBeInTheDocument();
    await user.click(within(form).getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(sent).toEqual({ first_name: 'Eve', last_name: 'Employee', email: 'eve@x.com' }));
  });
});
