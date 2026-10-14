/**
 * Client-side mirror of the backend RBAC rules, used only to decide which
 * actions to show. The backend remains the source of truth.
 */

export const ROLES = ['admin', 'manager', 'employee'];
export const MAX_WEEKLY_HOURS = 40;

const isAdmin = (user) => user?.role === 'admin';
const isManager = (user) => user?.role === 'manager';
const managesProject = (user, project) => isAdmin(user) || (isManager(user) && project?.manager_id === user.id);

/**
 * Decide whether the user may perform an action.
 *
 * @param {object} user Current user
 * @param {string} action Action name
 * @param {object} [context] Optional entity (project, request, time entry)
 * @returns {boolean}
 */
export function can(user, action, context) {
  if (!user) return false;
  switch (action) {
    case 'users:create':
    case 'users:edit':
    case 'users:resetPassword':
    case 'projects:create':
    case 'projects:archive':
    case 'projects:editAll':
    case 'requests:review':
    case 'audit:view':
      return isAdmin(user);
    case 'users:list':
    case 'requests:view':
    case 'allocation:view':
    case 'timesheets:approve':
      return isAdmin(user) || isManager(user);
    case 'requests:create':
      return isManager(user);
    case 'timesheets:log':
      return user.role === 'employee';
    case 'requests:edit':
      return context?.requested_by === user.id && context?.status === 'pending';
    case 'projects:edit':
    case 'resources:manage':
    case 'deliverables:manage':
    case 'budgets:manage':
      return managesProject(user, context) && !context?.is_archived;
    case 'budgets:breakdown':
      return managesProject(user, context);
    case 'timesheets:review':
      // context: a time entry
      return Boolean(context) && context.user_id !== user.id && context.status === 'pending'
        && (isAdmin(user) || (isManager(user) && context.user_manager_id === user.id));
    default:
      return false;
  }
}
