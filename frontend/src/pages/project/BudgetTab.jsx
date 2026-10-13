import { useState } from 'react';
import { budgetsApi } from '../../api/services';
import BudgetBar from '../../components/BudgetBar';
import { DataTable } from '../../components/DataTable';
import { Alert, EmptyState, ErrorState, Loading } from '../../components/Feedback';
import FormField from '../../components/FormField';
import { Modal } from '../../components/Modal';
import { Card, StatCard } from '../../components/PageParts';
import { useAsync } from '../../hooks/useAsync';
import { centsToDollars, dollarsToCents, formatCents, formatHours } from '../../utils/format';

const pct = (share) => (share === null || share === undefined ? '—' : `${Math.round(share * 100)}%`);

/**
 * Set a project's budget in dollars (stored as whole cents).
 *
 * @param {{budget: number, onSave: Function, onClose: Function}} props
 */
function BudgetDialog({ budget, onSave, onClose }) {
  const [value, setValue] = useState(centsToDollars(budget));
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      await onSave(dollarsToCents(value) ?? 0);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };
  return (
    <Modal title="Set budget" onClose={onClose} size="sm" footer={(
      <>
        <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button type="submit" form="budget-form" className="btn btn-primary" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
      </>
    )}>
      <form id="budget-form" className="form-stack" onSubmit={submit}>
        {error && <Alert kind="error">{error}</Alert>}
        <FormField label="Budget (USD)" required>
          <input type="number" min="0" step="0.01" inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} />
        </FormField>
      </form>
    </Modal>
  );
}

/**
 * Budget vs planned (from bookings) vs consumed (from approved hours).
 *
 * @param {{project: object, canManage: boolean, onChanged: Function}} props
 */
export default function BudgetTab({ project, canManage, onChanged }) {
  const [editing, setEditing] = useState(false);
  const { data, error, loading, reload } = useAsync(() => budgetsApi.get(project.id), `budget-${project.id}`);
  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;

  const peopleColumns = [
    { key: 'full_name', label: 'Person', render: (p) => <div className="cell-title"><strong>{p.full_name}</strong><span className="muted">{p.job_title}</span></div> },
    { key: 'planned', label: 'Planned', className: 'num', render: (p) => `${formatHours(p.planned_hours)} · ${formatCents(p.planned_cents)}` },
    { key: 'consumed', label: 'Consumed', className: 'num', render: (p) => `${formatHours(p.approved_hours)} · ${formatCents(p.consumed_cents)}` },
  ];

  return (
    <div className="tab-panel">
      <div className="stats-grid">
        <StatCard label="Budget" value={formatCents(data.budget_cents)} hint={canManage && (
          <button type="button" className="link-btn" onClick={() => setEditing(true)}>Change budget</button>
        )} />
        <StatCard label="Planned cost" value={formatCents(data.planned_cents)}
          tone={data.budget_cents && data.planned_cents > data.budget_cents ? 'warning' : 'default'}
          hint={data.unplanned_cents >= 0 ? `${formatCents(data.unplanned_cents)} unallocated` : `${formatCents(-data.unplanned_cents)} over budget`} />
        <StatCard label="Consumed" value={formatCents(data.consumed_cents)} tone={data.over_burn ? 'danger' : 'default'}
          hint={`${pct(data.consumed_share)} of budget · ${pct(data.elapsed_share)} of schedule`} />
        <StatCard label="Remaining" value={formatCents(data.remaining_cents)} tone={data.remaining_cents < 0 ? 'danger' : 'default'} />
      </div>

      <Card title="Consumed vs planned">
        <BudgetBar budget={data.budget_cents} planned={data.planned_cents} consumed={data.consumed_cents} />
        <p className="muted formula">
          Hourly rate = annual salary ÷ 2080. Planned = hours per week × weeks booked × rate.
          Consumed = approved logged hours × rate. Only approved hours count.
        </p>
        {data.over_burn && (
          <Alert kind="error">Budget is being consumed faster than the schedule: {pct(data.consumed_share)} spent with {pct(data.elapsed_share)} of the time elapsed.</Alert>
        )}
      </Card>

      {data.people && (
        <div className="two-col">
          <Card title="By person">
            <DataTable caption="Cost by person" columns={peopleColumns} rows={data.people.map((p) => ({ ...p, id: p.user_id }))}
              empty={<EmptyState title="Nobody is booked yet" />} />
          </Card>
          <Card title="Consumed by month">
            {data.by_month.length ? (
              <ul className="bar-list">
                {data.by_month.map((m) => (
                  <li key={m.month}>
                    <span className="bar-label">{new Date(`${m.month}T00:00:00`).toLocaleDateString('en-US', { month: 'short', year: 'numeric' })}</span>
                    <span className="bar-track"><span className="bar-fill fill-in_progress"
                      style={{ width: `${(m.consumed_cents / Math.max(...data.by_month.map((x) => x.consumed_cents), 1)) * 100}%` }} /></span>
                    <strong>{formatCents(m.consumed_cents)}</strong>
                  </li>
                ))}
              </ul>
            ) : <EmptyState title="No approved hours yet" />}
          </Card>
        </div>
      )}

      {editing && (
        <BudgetDialog
          budget={data.budget_cents}
          onClose={() => setEditing(false)}
          onSave={async (cents) => {
            await budgetsApi.set(project.id, cents);
            setEditing(false);
            reload();
            onChanged();
          }}
        />
      )}
    </div>
  );
}
