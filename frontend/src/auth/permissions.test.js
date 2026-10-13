import { describe, expect, it } from 'vitest';
import { USERS } from '../test/mockApi';
import { can } from './permissions';

const { admin, manager, employee } = USERS;
const ownProject = { id: 10, manager_id: manager.id, is_archived: false };
const otherProject = { id: 11, manager_id: 99, is_archived: false };
const archived = { ...ownProject, is_archived: true };

describe('can()', () => {
  it('denies everything without a user or for unknown actions', () => {
    expect(can(null, 'projects:create')).toBe(false);
    expect(can(admin, 'something:else')).toBe(false);
  });

  it.each([
    ['users:create', true, false, false],
    ['users:list', true, true, false],
    ['projects:create', true, false, false],
    ['projects:archive', true, false, false],
    ['projects:editAll', true, false, false],
    ['requests:create', false, true, false],
    ['requests:review', true, false, false],
    ['allocation:view', true, true, false],
    ['timesheets:approve', true, true, false],
    ['timesheets:log', false, false, true],
    ['audit:view', true, false, false],
  ])('%s → admin %s, manager %s, employee %s', (action, a, m, e) => {
    expect(can(admin, action)).toBe(a);
    expect(can(manager, action)).toBe(m);
    expect(can(employee, action)).toBe(e);
  });

  it('managers manage only their own, non-archived projects', () => {
    expect(can(manager, 'projects:edit', ownProject)).toBe(true);
    expect(can(manager, 'resources:manage', otherProject)).toBe(false);
    expect(can(manager, 'deliverables:manage', archived)).toBe(false);
    expect(can(admin, 'budgets:manage', otherProject)).toBe(true);
    expect(can(admin, 'projects:edit', archived)).toBe(false);
    expect(can(employee, 'projects:edit', ownProject)).toBe(false);
  });

  it('per-person costs are for admins and the project manager', () => {
    expect(can(manager, 'budgets:breakdown', ownProject)).toBe(true);
    expect(can(manager, 'budgets:breakdown', otherProject)).toBe(false);
    expect(can(employee, 'budgets:breakdown', ownProject)).toBe(false);
  });

  it('managers review their direct reports; admins anyone; nobody themselves', () => {
    const report = { user_id: 3, user_manager_id: manager.id, status: 'pending' };
    const stranger = { user_id: 9, user_manager_id: 42, status: 'pending' };
    expect(can(manager, 'timesheets:review', report)).toBe(true);
    expect(can(manager, 'timesheets:review', stranger)).toBe(false);
    expect(can(admin, 'timesheets:review', stranger)).toBe(true);
    expect(can(admin, 'timesheets:review', { ...stranger, status: 'approved' })).toBe(false);
    expect(can(manager, 'timesheets:review', { user_id: manager.id, user_manager_id: 1, status: 'pending' })).toBe(false);
  });

  it('only the requester edits a pending request', () => {
    expect(can(manager, 'requests:edit', { requested_by: manager.id, status: 'pending' })).toBe(true);
    expect(can(manager, 'requests:edit', { requested_by: manager.id, status: 'approved' })).toBe(false);
    expect(can(admin, 'requests:edit', { requested_by: manager.id, status: 'pending' })).toBe(false);
  });
});
