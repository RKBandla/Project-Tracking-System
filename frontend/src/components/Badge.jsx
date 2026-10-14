import { label } from '../utils/format';

const TONES = {
  planned: 'neutral',
  active: 'info',
  on_hold: 'warning',
  completed: 'success',
  at_risk: 'danger',
  on_track: 'success',
  pending: 'warning',
  approved: 'success',
  rejected: 'danger',
  withdrawn: 'neutral',
  todo: 'neutral',
  in_progress: 'info',
  blocked: 'danger',
  done: 'success',
  admin: 'accent',
  manager: 'info',
  employee: 'neutral',
  archived: 'neutral',
  create: 'success',
  update: 'info',
  archive: 'neutral',
  inactive: 'danger',
};

/**
 * Coloured pill for a status, health, role or other enum value.
 *
 * @param {{value: string, text?: string, dot?: boolean}} props
 */
export default function Badge({ value, text, dot = false }) {
  const tone = TONES[value] || 'neutral';
  return (
    <span className={`badge badge-${tone}`}>
      {dot && <span className="badge-dot" aria-hidden="true" />}
      {text || label(value)}
    </span>
  );
}
