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
 * @param {object} [context] Optional entity (project, user, request)
 * @returns {boolean}
 */
export function can(user, action, context) {
  if (!user) return false;
  switch (action) {
    case 'users:list':
      return isAdmin(user) || isManager(user);
    case 'users:create':
    case 'users:edit':
    case 'users:resetPassword':
    case 'projects:create':
    case 'projects:archive':
    case 'projects:assignManager':
    case 'requests:review':
      return isAdmin(user);
    case 'requests:view':
      return isAdmin(user) || isManager(user);
    case 'requests:create':
      return isManager(user);
    case 'requests:edit':
      return context?.requested_by === user.id && context?.status === 'pending';
    case 'projects:edit':
    case 'projects:manageTeam':
    case 'deliverables:manage':
    case 'budgets:manage':
      return managesProject(user, context) && !context?.is_archived;
    case 'budgets:view':
      return managesProject(user, context);
    case 'assignments:assignUser':
      // context: { project, person }
      return Boolean(context?.project && context?.person)
        && managesProject(user, context.project)
        && (isAdmin(user) || context.person.manager_id === user.id);
    default:
      return false;
  }
}
