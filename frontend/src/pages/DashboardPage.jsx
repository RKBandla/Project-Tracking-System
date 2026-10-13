import { projectsApi } from '../api/services';
import { useAuth } from '../auth/useAuth';
import Badge from '../components/Badge';
import { EmptyState, ErrorState, Loading } from '../components/Feedback';
import HoursBar from '../components/HoursBar';
import { Card, PageHeader, StatCard } from '../components/PageParts';
import { useAsync } from '../hooks/useAsync';
import { Link } from '../router/Router';
import { formatDate, formatMoney, label, today } from '../utils/format';

const HEALTH = ['green', 'amber', 'red'];

function HealthBreakdown({ byHealth, total }) {
  if (!total) return <EmptyState title="No active projects yet" />;
  return (
    <div>
      <div className="stacked-bar" role="img" aria-label={HEALTH.map((h) => `${byHealth[h]} ${label(h)}`).join(', ')}>
        {HEALTH.map((h) => byHealth[h] > 0 && (
          <span key={h} className={`seg seg-${h}`} style={{ flexGrow: byHealth[h] }} />
        ))}
      </div>
      <ul className="legend">
        {HEALTH.map((h) => (
          <li key={h}><span className={`legend-dot seg-${h}`} aria-hidden="true" />{label(h)} <strong>{byHealth[h]}</strong></li>
        ))}
      </ul>
    </div>
  );
}

function ProjectList({ projects }) {
  if (!projects.length) return <EmptyState title="Nothing at risk">All active projects are on track.</EmptyState>;
  return (
    <ul className="item-list">
      {projects.map((p) => (
        <li key={p.id}>
          <Link to={`/projects/${p.id}`} className="item-link">
            <span>
              <strong>{p.name}</strong>
              <span className="muted"> {p.code} · ends {formatDate(p.end_date)}</span>
            </span>
            <Badge value={p.health} dot />
          </Link>
        </li>
      ))}
    </ul>
  );
}

function DeliverableList({ items }) {
  if (!items.length) return <EmptyState title="Nothing due in the next two weeks" />;
  return (
    <ul className="item-list">
      {items.map((d) => (
        <li key={d.id}>
          <Link to={`/projects/${d.project_id}?tab=deliverables`} className="item-link">
            <span>
              <strong>{d.title}</strong>
              <span className="muted"> {d.project_name}</span>
            </span>
            <span className={`due ${d.due_date < today() ? 'overdue' : ''}`}>
              {formatDate(d.due_date)}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function CapacityList({ team }) {
  if (!team.length) return <EmptyState title="No people to show" />;
  return (
    <ul className="capacity-list">
      {team.map((person) => (
        <li key={person.id}>
          <div>
            <strong>{person.full_name}</strong>
            <span className="muted"> {person.job_title}</span>
          </div>
          <HoursBar hours={person.allocated_hours} compact />
        </li>
      ))}
    </ul>
  );
}

/** Role-specific overview: health, deadlines, capacity and requests. */
export default function DashboardPage() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useAsync(() => projectsApi.dashboard(), 'dashboard');

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;

  const atRisk = data.projects_by_health.amber + data.projects_by_health.red;
  const isEmployee = user.role === 'employee';

  return (
    <>
      <PageHeader
        eyebrow={new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
        title={`Welcome back, ${user.first_name}`}
        subtitle={isEmployee ? 'Here is what you are working on.' : 'Here is how your portfolio is doing.'}
      />

      <div className="stats-grid">
        <StatCard
          label={isEmployee ? 'My projects' : 'Active portfolio'}
          value={data.projects_total}
          hint={`${data.projects_by_status.active} active · ${data.projects_by_status.planned} planned`}
        />
        <StatCard label="At risk" value={atRisk} tone={atRisk ? 'warning' : 'default'}
          hint={`${data.projects_by_health.red} off track`} />
        <StatCard label="Overdue deliverables" value={data.overdue_deliverables}
          tone={data.overdue_deliverables ? 'danger' : 'default'} hint={isEmployee ? 'Assigned to you' : 'Across projects'} />
        {isEmployee ? (
          <StatCard label="My weekly hours" value={`${data.my_hours.allocated} h`}
            hint={`${data.my_hours.remaining} h available of ${data.max_weekly_hours}`} />
        ) : (
          <StatCard label="Pending requests" value={data.pending_requests}
            tone={data.pending_requests ? 'info' : 'default'}
            hint={<Link to="/requests">{user.role === 'admin' ? 'Review requests' : 'View my requests'}</Link>} />
        )}
      </div>

      <div className="dashboard-grid">
        <Card title="Project health">
          <HealthBreakdown byHealth={data.projects_by_health} total={data.projects_total} />
        </Card>
        {!isEmployee && data.budget && (
          <Card title="Budget">
            <div className="budget-mini">
              <div><span className="muted">Total budget</span><strong>{formatMoney(data.budget.budget_total)}</strong></div>
              <div><span className="muted">Planned</span><strong>{formatMoney(data.budget.planned)}</strong></div>
              <div><span className="muted">Spent</span><strong>{formatMoney(data.budget.actual)}</strong></div>
            </div>
          </Card>
        )}
        {isEmployee && (
          <Card title="My assignments" actions={<HoursBar hours={data.my_hours.allocated} compact />}>
            {data.my_assignments.length ? (
              <ul className="item-list">
                {data.my_assignments.map((a) => (
                  <li key={a.project_id}>
                    <Link to={`/projects/${a.project_id}`} className="item-link">
                      <span><strong>{a.project_name}</strong><span className="muted"> {a.project_role}</span></span>
                      <span className="pill">{a.hours_per_week} h/wk</span>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : <EmptyState title="You are not assigned to any projects yet" />}
          </Card>
        )}
        <Card title="Needs attention">
          <ProjectList projects={data.at_risk_projects} />
        </Card>
        <Card title={isEmployee ? 'My upcoming deliverables' : 'Due in the next 14 days'}>
          <DeliverableList items={data.upcoming_deliverables} />
        </Card>
        {!isEmployee && data.capacity && (
          <Card
            title={user.role === 'admin' ? 'Team capacity' : 'My team capacity'}
            className="span-2"
            actions={(
              <span className="muted">
                {data.capacity.available_hours} h available · {data.capacity.fully_allocated} fully allocated
              </span>
            )}
          >
            <CapacityList team={data.capacity.team} />
          </Card>
        )}
      </div>
    </>
  );
}
