import { projectsApi } from '../api/services';
import { useAuth } from '../auth/useAuth';
import Badge from '../components/Badge';
import BudgetBar from '../components/BudgetBar';
import { EmptyState, ErrorState, Loading } from '../components/Feedback';
import { Card, PageHeader, StatCard } from '../components/PageParts';
import { useAsync } from '../hooks/useAsync';
import { Link } from '../router/Router';
import { PROJECT_STATUSES } from '../utils/constants';
import { formatDate, formatHours, label, today } from '../utils/format';

function StatusBreakdown({ byStatus }) {
  const total = Object.values(byStatus).reduce((a, b) => a + b, 0);
  if (!total) return <EmptyState title="No active projects yet" />;
  return (
    <ul className="bar-list">
      {PROJECT_STATUSES.map((s) => (
        <li key={s}>
          <span className="bar-label">{label(s)}</span>
          <span className="bar-track"><span className={`bar-fill fill-${s}`} style={{ width: `${(byStatus[s] / total) * 100}%` }} /></span>
          <strong>{byStatus[s]}</strong>
        </li>
      ))}
    </ul>
  );
}

function AtRiskList({ projects }) {
  if (!projects.length) return <EmptyState title="Nothing at risk">Every active project is on track.</EmptyState>;
  return (
    <ul className="item-list">
      {projects.map((p) => (
        <li key={p.id}>
          <Link to={`/projects/${p.id}`} className="item-link item-link-stack">
            <span className="item-row">
              <strong>{p.name}</strong>
              <Badge value="at_risk" dot />
            </span>
            <span className="muted">{p.code} · {p.manager_name || 'No manager'} · ends {formatDate(p.end_date)}</span>
            <ul className="reason-list">
              {p.risk_reasons.map((r) => <li key={r}>{r}</li>)}
            </ul>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function DeliverableList({ items }) {
  if (!items.length) return <EmptyState title="Nothing due in the next two weeks" />;
  const now = today();
  return (
    <ul className="item-list">
      {items.map((d) => (
        <li key={d.id}>
          <Link to={`/projects/${d.project_id}?tab=deliverables`} className="item-link">
            <span><strong>{d.title}</strong><span className="muted"> {d.project_name}</span></span>
            <span className={`due ${d.due_date < now ? 'overdue' : ''}`}>{formatDate(d.due_date)}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

/** Role-specific overview: status, risk with reasons, deadlines, budget, capacity, approvals. */
export default function DashboardPage() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useAsync(() => projectsApi.dashboard(), 'dashboard');

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;

  const isEmployee = user.role === 'employee';
  return (
    <>
      <PageHeader
        eyebrow={new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
        title={`Welcome back, ${user.first_name}`}
        subtitle={isEmployee ? 'Here is what you are working on.' : 'Here is how your projects are doing.'}
      />

      <div className="stats-grid">
        <StatCard
          label={isEmployee ? 'My projects' : 'Active projects'}
          value={data.projects_total}
          hint={`${data.projects_by_status.active} active · ${data.projects_by_status.on_hold} on hold`}
        />
        <StatCard label="At risk" value={data.at_risk_count} tone={data.at_risk_count ? 'danger' : 'default'}
          hint={<Link to="/projects?at_risk=true">See at-risk projects</Link>} />
        <StatCard label="Overdue deliverables" value={data.overdue_deliverables}
          tone={data.overdue_deliverables ? 'warning' : 'default'} hint={isEmployee ? 'Assigned to you' : 'Across projects'} />
        {isEmployee ? (
          <StatCard label="Booked this week" value={formatHours(data.my_week_hours)}
            hint={<Link to="/timesheet">{formatHours(data.my_logged_this_week.pending)} pending · {formatHours(data.my_logged_this_week.approved)} approved</Link>} />
        ) : (
          <StatCard label="Hours to approve" value={data.hours_to_approve}
            tone={data.hours_to_approve ? 'info' : 'default'}
            hint={<Link to="/approvals">Review timesheets</Link>} />
        )}
      </div>

      <div className="dashboard-grid">
        <Card title="At risk" className="span-2" actions={<span className="muted">{data.at_risk_count} of {data.projects_total}</span>}>
          <AtRiskList projects={data.at_risk_projects} />
        </Card>
        <Card title="Projects by status">
          <StatusBreakdown byStatus={data.projects_by_status} />
        </Card>
        <Card title="Budget: consumed vs planned">
          <BudgetBar budget={data.budget.budget_cents} planned={data.budget.planned_cents} consumed={data.budget.consumed_cents} />
        </Card>
        <Card title={isEmployee ? 'My upcoming deliverables' : 'Due in the next 14 days'}>
          <DeliverableList items={data.upcoming_deliverables} />
        </Card>
        {isEmployee ? (
          <Card title="My bookings">
            {data.my_assignments.length ? (
              <ul className="item-list">
                {data.my_assignments.map((a) => (
                  <li key={a.id}>
                    <Link to={`/projects/${a.project_id}`} className="item-link">
                      <span><strong>{a.project_name}</strong><span className="muted"> {formatDate(a.start_date)} – {formatDate(a.end_date)}</span></span>
                      <span className="pill">{a.hours_per_week} h/wk</span>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : <EmptyState title="You are not booked on any projects yet" />}
          </Card>
        ) : (
          <Card title="Fully booked (next 8 weeks)" actions={<Link to="/allocation">Allocation grid</Link>}>
            {data.fully_booked_people.length ? (
              <ul className="item-list">
                {data.fully_booked_people.map((p) => (
                  <li key={p.id} className="item-link">
                    <span><strong>{p.full_name}</strong><span className="muted"> {p.job_title}</span></span>
                    <span className="pill pill-danger">{p.peak_hours} h</span>
                  </li>
                ))}
              </ul>
            ) : <EmptyState title="Nobody is at 40 hours" />}
          </Card>
        )}
        {!isEmployee && (
          <Card title="Waiting on you">
            <ul className="item-list">
              <li><Link className="item-link" to="/approvals"><span>Hours to approve</span><span className="pill">{data.hours_to_approve}</span></Link></li>
              <li><Link className="item-link" to="/requests"><span>{user.role === 'admin' ? 'Project requests to review' : 'My pending requests'}</span><span className="pill">{data.pending_requests}</span></Link></li>
              <li><Link className="item-link" to="/notifications"><span>Unread notifications</span><span className="pill">{data.unread_notifications}</span></Link></li>
            </ul>
          </Card>
        )}
      </div>
    </>
  );
}
