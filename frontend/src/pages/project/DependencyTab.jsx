import { deliverablesApi } from '../../api/services';
import Badge from '../../components/Badge';
import { EmptyState, ErrorState, Loading } from '../../components/Feedback';
import MilestoneMark from '../../components/MilestoneMark';
import { Card } from '../../components/PageParts';
import { useAsync } from '../../hooks/useAsync';
import { formatDate } from '../../utils/format';

/**
 * Dependency view: deliverables arranged in columns so everything a deliverable
 * depends on sits in an earlier column. Scrolls sideways on narrow screens.
 *
 * @param {{project: object}} props
 */
export default function DependencyTab({ project }) {
  const { data, error, loading, reload } = useAsync(() => deliverablesApi.graph(project.id), `graph-${project.id}`);
  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;

  const byId = Object.fromEntries(data.nodes.map((n) => [n.id, n]));
  const dependents = {};
  data.edges.forEach((e) => { (dependents[e.from] ||= []).push(e.to); });
  const levels = [];
  data.nodes.forEach((n) => { (levels[n.level] ||= []).push(n); });

  return (
    <div className="tab-panel">
      <Card title="Dependency chain" actions={<span className="muted">{data.nodes.length} deliverables · {data.edges.length} links</span>}>
        {data.nodes.length === 0 ? (
          <EmptyState title="No deliverables yet" />
        ) : (
          <div className="dep-scroll">
            <ol className="dep-columns" aria-label="Deliverables in dependency order">
              {levels.map((nodes, level) => (
                <li key={level} className="dep-column">
                  <h3>{level === 0 ? 'Can start now' : `Step ${level + 1}`}</h3>
                  {nodes.map((n) => (
                    <article key={n.id} className={`dep-card status-${n.status} ${n.is_blocked && n.status !== 'done' ? 'blocked' : ''}`}>
                      <header>
                        <strong>{n.is_milestone && <MilestoneMark />} {n.title}</strong>
                        <Badge value={n.status} />
                      </header>
                      <p className="muted">{n.assignee_name || 'Unassigned'} · due {formatDate(n.due_date)}</p>
                      {n.depends_on.length > 0 && (
                        <p className="dep-links">
                          <span aria-hidden="true">← </span>after {n.depends_on.map((id) => byId[id]?.title || `#${id}`).join(', ')}
                        </p>
                      )}
                      {dependents[n.id] && (
                        <p className="dep-links">
                          <span aria-hidden="true">→ </span>unblocks {dependents[n.id].map((id) => byId[id]?.title).join(', ')}
                        </p>
                      )}
                      {n.is_blocked && n.status !== 'done' && <p className="text-danger dep-note">Waiting on unfinished work</p>}
                    </article>
                  ))}
                </li>
              ))}
            </ol>
          </div>
        )}
      </Card>
    </div>
  );
}
