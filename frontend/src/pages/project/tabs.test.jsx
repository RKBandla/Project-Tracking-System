import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { USERS } from '../../test/mockApi';
import { renderApp } from '../../test/renderApp';

const project = {
  id: 7, code: 'PRJ-0007', name: 'Apollo', description: '', status: 'active', health: 'green',
  start_date: null, end_date: null, manager_id: USERS.manager.id, manager_name: 'Max Manager',
  budget_total: 1000, is_archived: false,
};
const summary = {
  project,
  deliverables: { total: 1, todo: 1, in_progress: 0, blocked: 0, done: 0, overdue: 0, avg_progress: 0, completion_pct: 0 },
  team: { size: 1, total_hours: 10, members: [{ id: 50, user_id: 3, employee_id: 'EMP0002', full_name: 'Eve Employee', job_title: 'Engineer', project_role: '', hours_per_week: 10 }] },
  budget: { planned: 0, actual: 0, budget_total: 1000, remaining: 1000, burn_pct: 0 },
};

describe('Deliverables tab', () => {
  it('creates, filters and deletes deliverables', async () => {
    let items = [{ id: 1, project_id: 7, title: 'Spec', description: '', status: 'todo', due_date: '2000-01-01', is_overdue: true, assignee_id: 3, assignee_name: 'Eve Employee', progress_pct: 20 }];
    const listQueries = [];
    let created;
    const { user } = renderApp({
      as: USERS.manager,
      path: '/projects/7?tab=deliverables',
      routes: {
        'GET /api/projects/7/summary': summary,
        'GET /api/deliverables': ({ url }) => {
          listQueries.push(Object.fromEntries(new URL(url, 'http://x').searchParams));
          return { items, total: items.length, page: 1, page_size: 100 };
        },
        'POST /api/deliverables': ({ body }) => {
          created = body;
          items = [...items, { ...body, id: 2, is_overdue: false, assignee_name: null }];
          return { status: 201, body: items[1] };
        },
        'DELETE /api/deliverables/1': () => { items = items.filter((d) => d.id !== 1); return { status: 204, body: null }; },
      },
    });

    expect(await screen.findByText('Spec')).toBeInTheDocument();
    expect(screen.getByText(/overdue/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'New deliverable' }));
    const dialog = screen.getByRole('dialog', { name: 'New deliverable' });
    const assignee = within(dialog).getByLabelText(/Assignee/);
    expect(within(assignee).getAllByRole('option').map((o) => o.textContent))
      .toEqual(['Unassigned', 'Max Manager (manager)', 'Eve Employee']);
    await user.type(within(dialog).getByLabelText(/Title/), 'Launch');
    await user.selectOptions(within(dialog).getByLabelText(/Status/), 'done');
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Launch')).toBeInTheDocument();
    expect(created).toMatchObject({ project_id: 7, title: 'Launch', status: 'done', progress_pct: 100, assignee_id: null });

    await user.selectOptions(screen.getByLabelText('Filter by status'), 'blocked');
    await waitFor(() => expect(listQueries.at(-1).status).toBe('blocked'));
    await user.selectOptions(screen.getByLabelText('Filter by status'), '');

    const row = (await screen.findByText('Spec')).closest('tr');
    await user.click(within(row).getByRole('button', { name: 'Delete' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(screen.queryByText('Spec')).not.toBeInTheDocument());
  });

  it('is read-only for employees', async () => {
    const data = { ...summary };
    delete data.budget;
    renderApp({
      as: USERS.employee,
      path: '/projects/7?tab=deliverables',
      routes: {
        'GET /api/projects/7/summary': data,
        'GET /api/deliverables': { items: [], total: 0, page: 1, page_size: 100 },
      },
    });
    expect(await screen.findByText('No deliverables yet')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'New deliverable' })).not.toBeInTheDocument();
  });
});

describe('Budget tab', () => {
  it('shows totals and adds an item', async () => {
    let items = [{ id: 1, project_id: 7, category: 'labor', description: 'Devs', planned_amount: 800, actual_amount: 1200, entry_date: '2026-02-01' }];
    const totals = () => ({
      planned: items.reduce((s, i) => s + i.planned_amount, 0),
      actual: items.reduce((s, i) => s + i.actual_amount, 0),
    });
    const { user } = renderApp({
      as: USERS.manager,
      path: '/projects/7?tab=budget',
      routes: {
        'GET /api/projects/7/summary': summary,
        'GET /api/budgets': () => ({ items, total: items.length, page: 1, page_size: 100, totals: totals() }),
        'POST /api/budgets': ({ body }) => {
          items = [...items, { ...body, id: 2 }];
          return { status: 201, body: items[1] };
        },
        'PUT /api/budgets/1': ({ body }) => {
          items = items.map((i) => (i.id === 1 ? { ...i, ...body } : i));
          return items[0];
        },
      },
    });

    expect(await screen.findByText('Devs')).toBeInTheDocument();
    expect(screen.getByText('Over budget')).toBeInTheDocument();
    expect(screen.getByText('-$200')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Add item' }));
    const dialog = screen.getByRole('dialog', { name: 'New budget item' });
    await user.type(within(dialog).getByLabelText(/Description/), 'Licences');
    await user.selectOptions(within(dialog).getByLabelText(/Category/), 'software');
    await user.type(within(dialog).getByLabelText(/Planned/), '100');
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Licences')).toBeInTheDocument();

    const row = screen.getByText('Devs').closest('tr');
    await user.click(within(row).getByRole('button', { name: 'Edit' }));
    const edit = screen.getByRole('dialog', { name: 'Edit budget item' });
    await user.clear(within(edit).getByLabelText(/Actual/));
    await user.type(within(edit).getByLabelText(/Actual/), '500');
    await user.click(within(edit).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(screen.queryByText('Over budget')).not.toBeInTheDocument());
  });
});

describe('Project form', () => {
  it('manager edits their project without a manager field', async () => {
    let sent;
    const { user } = renderApp({
      as: USERS.manager,
      path: '/projects/7',
      routes: {
        'GET /api/projects/7/summary': summary,
        'PUT /api/projects/7': ({ body }) => { sent = body; return { ...project, ...body }; },
      },
    });
    await user.click(await screen.findByRole('button', { name: 'Edit' }));
    const dialog = screen.getByRole('dialog', { name: 'Edit PRJ-0007' });
    expect(within(dialog).queryByLabelText(/Project manager/)).not.toBeInTheDocument();
    await user.selectOptions(within(dialog).getByLabelText(/Health/), 'red');
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(sent).toMatchObject({ health: 'red', name: 'Apollo', start_date: null }));
    expect(sent).not.toHaveProperty('manager_id');
  });

  it('admin creates a project and assigns a manager', async () => {
    let sent;
    const { user } = renderApp({
      as: USERS.admin,
      path: '/projects',
      routes: {
        'GET /api/projects': { items: [], total: 0, page: 1, page_size: 20 },
        'GET /api/users': { items: [USERS.manager, USERS.employee], total: 2, page: 1, page_size: 100 },
        'POST /api/projects': ({ body }) => { sent = body; return { status: 201, body: { ...project, id: 8 } }; },
        'GET /api/projects/8/summary': { ...summary, project: { ...project, id: 8 } },
      },
    });
    await user.click(await screen.findByRole('button', { name: 'New project' }));
    const dialog = screen.getByRole('dialog', { name: 'New project' });
    const managerSelect = within(dialog).getByLabelText(/Project manager/);
    await waitFor(() => expect(within(managerSelect).getAllByRole('option')).toHaveLength(2));
    await user.type(within(dialog).getByLabelText(/Name/), 'Hermes');
    await user.selectOptions(managerSelect, String(USERS.manager.id));
    await user.type(within(dialog).getByLabelText(/Total budget/), '2500');
    await user.click(within(dialog).getByRole('button', { name: 'Create project' }));
    expect(await screen.findByRole('heading', { name: 'Apollo' })).toBeInTheDocument();
    expect(sent).toMatchObject({ name: 'Hermes', manager_id: USERS.manager.id, budget_total: 2500 });
  });
});

describe('Request form', () => {
  it('manager submits a project request', async () => {
    let sent;
    const { user } = renderApp({
      as: USERS.manager,
      path: '/requests?new=1',
      routes: {
        'GET /api/project-requests': { items: [], total: 0, page: 1, page_size: 20 },
        'POST /api/project-requests': ({ body }) => { sent = body; return { status: 201, body: { id: 1, ...body, status: 'pending' } }; },
      },
    });
    const dialog = await screen.findByRole('dialog', { name: 'Request a new project' });
    await user.type(within(dialog).getByLabelText(/Project name/), 'Atlas');
    await user.type(within(dialog).getByLabelText(/justification/), 'Customers need it');
    await user.type(within(dialog).getByLabelText(/Proposed budget/), '9000');
    await user.click(within(dialog).getByRole('button', { name: 'Submit request' }));
    expect(await screen.findByText('Request submitted. An admin will review it.')).toBeInTheDocument();
    expect(sent).toMatchObject({ name: 'Atlas', justification: 'Customers need it', proposed_budget: 9000, proposed_start_date: null });
    expect(window.location.search).toBe('');
  });
});
