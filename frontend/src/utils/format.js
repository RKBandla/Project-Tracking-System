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
  green: 'On track',
  amber: 'At risk',
  red: 'Off track',
  pending: 'Pending',
  approved: 'Approved',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
  todo: 'To do',
  in_progress: 'In progress',
  blocked: 'Blocked',
  done: 'Done',
  labor: 'Labor',
  software: 'Software',
  hardware: 'Hardware',
  travel: 'Travel',
  services: 'Services',
  other: 'Other',
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
