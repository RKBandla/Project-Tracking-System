import { Card, DetailList, StatCard } from '../../components/PageParts';
import { formatDate, formatMoney, label } from '../../utils/format';

const STATUS_ORDER = ['todo', 'in_progress', 'blocked', 'done'];

/**
 * Project health at a glance: delivery, team and budget.
 *
 * @param {{summary: object}} props
 */
export default function OverviewTab({ summary }) {
  const { project, deliverables: d, team, budget } = summary;
  return (
    <div className="tab-panel">
      <div className="stats-grid">
        <StatCard label="Completion" value={`${d.completion_pct}%`} hint={`${d.done} of ${d.total} deliverables done`} />
        <StatCard label="Overdue" value={d.overdue} tone={d.overdue ? 'danger' : 'default'} hint={`${d.blocked} blocked`} />
        <StatCard label="Team" value={team.size} hint={`${team.total_hours} hours per week`} />
        {budget && (
          <StatCard
            label="Budget used"
            value={`${budget.burn_pct}%`}
            tone={budget.burn_pct > 100 ? 'danger' : budget.burn_pct > 85 ? 'warning' : 'default'}
            hint={`${formatMoney(budget.actual)} of ${formatMoney(budget.budget_total)}`}
          />
        )}
      </div>

      <div className="two-col">
        <Card title="Details">
          <DetailList
            items={[
              ['Code', project.code],
              ['Manager', project.manager_name || 'Unassigned'],
              ['Status', label(project.status)],
              ['Health', label(project.health)],
              ['Start', formatDate(project.start_date)],
              ['End', formatDate(project.end_date)],
              ...(budget ? [['Budget', formatMoney(project.budget_total)], ['Remaining', formatMoney(budget.remaining)]] : []),
              ...(project.is_archived ? [['Archived', formatDate(project.archived_at)]] : []),
            ]}
          />
        </Card>
        <Card title="Deliverables by status">
          {d.total ? (
            <ul className="bar-list">
              {STATUS_ORDER.map((s) => (
                <li key={s}>
                  <span className="bar-label">{label(s)}</span>
                  <span className="bar-track">
                    <span className={`bar-fill fill-${s}`} style={{ width: `${(d[s] / d.total) * 100}%` }} />
                  </span>
                  <strong>{d[s]}</strong>
                </li>
              ))}
            </ul>
          ) : <p className="muted">No deliverables yet.</p>}
        </Card>
      </div>

      {project.description && (
        <Card title="Description">
          <p className="prewrap">{project.description}</p>
        </Card>
      )}
    </div>
  );
}
