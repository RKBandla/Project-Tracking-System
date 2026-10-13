import { formatCents } from '../utils/format';

/**
 * Budget bar: the track is the budget, with consumed (solid) and planned (marker) cost.
 *
 * @param {{budget: number, planned: number, consumed: number, compact?: boolean}} props All in cents
 */
export default function BudgetBar({ budget, planned, consumed, compact = false }) {
  const scale = Math.max(budget, planned, consumed, 1);
  const pct = (value) => `${Math.min(100, (value / scale) * 100)}%`;
  const over = budget > 0 && consumed > budget;
  const consumedShare = budget > 0 ? Math.round((consumed / budget) * 100) : null;
  return (
    <div className={`budget-bar ${compact ? 'budget-bar-compact' : ''}`}>
      <div
        className="budget-track"
        role="img"
        aria-label={`${formatCents(consumed)} consumed and ${formatCents(planned)} planned of a ${formatCents(budget)} budget`}
      >
        {budget > 0 && <span className="budget-limit" style={{ left: pct(budget) }} />}
        <span className={`budget-consumed ${over ? 'over' : ''}`} style={{ width: pct(consumed) }} />
        <span className="budget-planned" style={{ left: pct(planned) }} title={`Planned ${formatCents(planned)}`} />
      </div>
      {!compact && (
        <div className="budget-legend">
          <span><i className="dot dot-consumed" aria-hidden="true" />Consumed {formatCents(consumed)}</span>
          <span><i className="dot dot-planned" aria-hidden="true" />Planned {formatCents(planned)}</span>
          <span><i className="dot dot-budget" aria-hidden="true" />Budget {formatCents(budget)}</span>
        </div>
      )}
      {compact && (
        <span className="muted budget-caption">
          {consumedShare === null ? 'No budget' : `${consumedShare}% of ${formatCents(budget)}`}
        </span>
      )}
    </div>
  );
}
