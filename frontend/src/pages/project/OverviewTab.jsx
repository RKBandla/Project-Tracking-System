import BudgetBar from '../../components/BudgetBar';
import { Alert } from '../../components/Feedback';
import { Card, DetailList, StatCard } from '../../components/PageParts';
import { DELIVERABLE_STATUSES } from '../../utils/constants';
import { formatCents, formatDate, label } from '../../utils/format';

/**
 * Project health at a glance: risk, delivery, team and budget.
 *
 * @param {{summary: object}} props
 */
export default function OverviewTab({ summary }) {
  const { project, deliverables: d, team, budget } = summary;
  const consumedPct = budget.consumed_share === null ? '—' : `${Math.round(budget.consumed_share * 100)}%`;
  return (
    <div className="tab-panel">
      {summary.at_risk && (
        <Alert kind="error">
          <div>
            <strong>At risk</strong>
            <ul className="reason-list">{summary.risk_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          </div>
        </Alert>
      )}
      <div className="stats-grid">
        <StatCard label="Completion" value={`${d.completion_pct}%`} hint={`${d.done} of ${d.total} deliverables done`} />
        <StatCard label="Overdue" value={d.overdue} tone={d.overdue ? 'danger' : 'default'} hint={`${d.blocked} blocked`} />
        <StatCard label="Team this week" value={team.size} hint={`${team.weekly_hours} hours booked`} />
        <StatCard label="Budget consumed" value={consumedPct} tone={project.over_burn ? 'danger' : 'default'}
          hint={`${formatCents(budget.consumed_cents)} of ${formatCents(budget.budget_cents)}`} />
      </div>

      <div className="two-col">
        <Card title="Details">
          <DetailList
            items={[
              ['Code', project.code],
              ['Manager', project.manager_name || 'Unassigned'],
              ['Status', label(project.status)],
              ['Start', formatDate(project.start_date)],
              ['End', formatDate(project.end_date)],
              ['Budget', formatCents(budget.budget_cents)],
              ['Planned cost', formatCents(budget.planned_cents)],
              ...(project.is_archived ? [['Archived', formatDate(project.archived_at)]] : []),
            ]}
          />
        </Card>
        <Card title="Deliverables by status">
          {d.total ? (
            <ul className="bar-list">
              {DELIVERABLE_STATUSES.map((s) => (
                <li key={s}>
                  <span className="bar-label">{label(s)}</span>
                  <span className="bar-track"><span className={`bar-fill fill-${s}`} style={{ width: `${(d[s] / d.total) * 100}%` }} /></span>
                  <strong>{d[s]}</strong>
                </li>
              ))}
            </ul>
          ) : <p className="muted">No deliverables yet.</p>}
        </Card>
      </div>

      <Card title="Budget">
        <BudgetBar budget={budget.budget_cents} planned={budget.planned_cents} consumed={budget.consumed_cents} />
      </Card>

      {project.description && (
        <Card title="Description"><p className="prewrap">{project.description}</p></Card>
      )}
    </div>
  );
}
