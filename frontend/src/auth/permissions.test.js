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
    ['users:edit', true, false, false],
    ['users:list', true, true, false],
    ['projects:create', true, false, false],
    ['projects:archive', true, false, false],
    ['projects:assignManager', true, false, false],
    ['requests:create', false, true, false],
    ['requests:review', true, false, false],
    ['requests:view', true, true, false],
  ])('%s → admin %s, manager %s, employee %s', (action, a, m, e) => {
    expect(can(admin, action)).toBe(a);
    expect(can(manager, action)).toBe(m);
    expect(can(employee, action)).toBe(e);
  });

  it('managers manage only their own, non-archived projects', () => {
    expect(can(manager, 'projects:edit', ownProject)).toBe(true);
    expect(can(manager, 'projects:edit', otherProject)).toBe(false);
    expect(can(manager, 'deliverables:manage', archived)).toBe(false);
    expect(can(admin, 'projects:edit', otherProject)).toBe(true);
    expect(can(admin, 'projects:edit', archived)).toBe(false);
    expect(can(employee, 'projects:edit', ownProject)).toBe(false);
  });

  it('budgets are visible to admins and the project manager only', () => {
    expect(can(admin, 'budgets:view', otherProject)).toBe(true);
    expect(can(manager, 'budgets:view', ownProject)).toBe(true);
    expect(can(manager, 'budgets:view', otherProject)).toBe(false);
    expect(can(employee, 'budgets:view', ownProject)).toBe(false);
  });

  it('managers can assign only their direct reports', () => {
    expect(can(manager, 'assignments:assignUser', { project: ownProject, person: employee })).toBe(true);
    expect(can(manager, 'assignments:assignUser', { project: ownProject, person: { id: 9, manager_id: 1 } })).toBe(false);
    expect(can(admin, 'assignments:assignUser', { project: otherProject, person: { id: 9, manager_id: 7 } })).toBe(true);
    expect(can(admin, 'assignments:assignUser', { project: otherProject })).toBe(false);
  });

  it('only the requester edits a pending request', () => {
    expect(can(manager, 'requests:edit', { requested_by: manager.id, status: 'pending' })).toBe(true);
    expect(can(manager, 'requests:edit', { requested_by: manager.id, status: 'approved' })).toBe(false);
    expect(can(admin, 'requests:edit', { requested_by: manager.id, status: 'pending' })).toBe(false);
  });
});
