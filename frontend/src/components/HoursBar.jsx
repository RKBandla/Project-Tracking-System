import { MAX_WEEKLY_HOURS } from '../auth/permissions';

/**
 * Weekly allocation meter (x of 40 hours).
 *
 * @param {{hours: number, max?: number, compact?: boolean}} props
 */
export default function HoursBar({ hours, max = MAX_WEEKLY_HOURS, compact = false }) {
  const value = Number(hours || 0);
  const pct = Math.min(100, Math.round((value / max) * 100));
  const tone = value >= max ? 'full' : value >= max * 0.75 ? 'high' : 'ok';
  return (
    <div className={`hours ${compact ? 'hours-compact' : ''}`}>
      <div
        className="hours-track"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={value}
        aria-label={`${value} of ${max} hours allocated`}
      >
        <div className={`hours-fill hours-${tone}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="hours-text">{value}/{max} h</span>
    </div>
  );
}
