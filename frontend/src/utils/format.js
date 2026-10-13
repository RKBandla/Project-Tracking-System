/**
 * Display formatting helpers.
 */

const LABELS = {
  admin: 'Admin',
  manager: 'Manager',
  employee: 'Employee',
  planned: 'Planned',
  active: 'Active',
  on_hold: 'On hold',
  completed: 'Completed',
  at_risk: 'At risk',
  on_track: 'On track',
  pending: 'Pending',
  approved: 'Approved',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
  todo: 'To do',
  in_progress: 'In progress',
  blocked: 'Blocked',
  done: 'Done',
  project_request: 'Project request',
  time_entry: 'Time entry',
  assignment: 'Assignment',
  deliverable: 'Deliverable',
  project: 'Project',
  user: 'User',
  create: 'Create',
  update: 'Edit',
  archive: 'Archive',
};

/** Human label for an enum value. */
export function label(value) {
  if (value === null || value === undefined) return '';
  return LABELS[value] || String(value).replace(/_/g, ' ');
}

/** Format an ISO date (YYYY-MM-DD or timestamp) as e.g. "Mar 4, 2026". */
export function formatDate(value) {
  if (!value) return '—';
  const [y, m, d] = String(value).slice(0, 10).split('-').map(Number);
  if (!y || !m || !d) return '—';
  return new Date(y, m - 1, d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

/** Format a number as US dollars without cents for whole amounts. */
export function formatMoney(value) {
  const n = Number(value || 0);
  return n.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: Number.isInteger(n) ? 0 : 2,
    maximumFractionDigits: 2,
  });
}

/** Format whole cents as dollars, e.g. 123456 -> "$1,234.56". */
export function formatCents(cents) {
  return formatMoney(Number(cents || 0) / 100);
}

/** Convert a dollar amount typed in a form to whole cents (null when empty). */
export function dollarsToCents(value) {
  if (value === '' || value === null || value === undefined) return null;
  return Math.round(Number(value) * 100);
}

/** Convert cents to a dollar string for a form input. */
export function centsToDollars(cents) {
  if (cents === null || cents === undefined) return '';
  return String(Number(cents) / 100);
}

/** Format hours, dropping trailing zeros (7.50 -> "7.5"). */
export function formatHours(value) {
  return `${Number(value || 0).toLocaleString('en-US', { maximumFractionDigits: 2 })} h`;
}

/** Add days to a YYYY-MM-DD date string. */
export function addDays(iso, days) {
  const [y, m, d] = iso.split('-').map(Number);
  const date = new Date(y, m - 1, d + days);
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** Monday of the week containing a YYYY-MM-DD date. */
export function mondayOf(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  const day = new Date(y, m - 1, d).getDay();
  return addDays(iso, -((day + 6) % 7));
}

/** Short day label, e.g. "Mon 5". */
export function formatDay(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString('en-US', { weekday: 'short', day: 'numeric' });
}

/** Short date for grid headers, e.g. "Jan 5". */
export function formatShortDate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

/** Relative time for notifications, e.g. "5 min ago". */
export function timeAgo(value, now = Date.now()) {
  const seconds = Math.max(0, Math.round((now - new Date(value).getTime()) / 1000));
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return formatDate(value);
}

/** Initials for an avatar. */
export function initials(name) {
  return String(name || '?')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join('');
}

/** Today's date as YYYY-MM-DD in local time. */
export function today() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Turn an ApiError into a field -> message map for forms. */
export function fieldErrors(error) {
  return error && typeof error.details === 'object' && !Array.isArray(error.details) ? error.details : {};
}
