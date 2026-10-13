import { useState } from 'react';
import { deliverablesApi } from '../../api/services';
import Badge from '../../components/Badge';
import { DataTable } from '../../components/DataTable';
import { EmptyState, ErrorState, Loading } from '../../components/Feedback';
import DeliverableForm from '../../components/forms/DeliverableForm';
import { ConfirmDialog } from '../../components/Modal';
import { Card, FilterBar } from '../../components/PageParts';
import { useAsync } from '../../hooks/useAsync';
import { useDebouncedValue } from '../../hooks/useDebouncedValue';
import { DELIVERABLE_STATUSES } from '../../utils/constants';
import { addDays, formatDate, formatShortDate, label, today } from '../../utils/format';

const DAY = 86_400_000;
const toTime = (iso) => new Date(`${iso}T00:00:00`).getTime();

/**
 * Timeline (Gantt-style) of deliverables: a bar from start to due date, scrolled sideways on phones.
 *
 * @param {{items: object[], project: object}} props
 */
function Timeline({ items, project }) {
  const dated = items.filter((d) => d.due_date || d.start_date);
  if (!dated.length) return <EmptyState title="Add start or due dates to see the timeline" />;
  const starts = dated.map((d) => d.start_date || d.due_date);
  const ends = dated.map((d) => d.due_date || d.start_date);
  const first = [project.start_date, ...starts].filter(Boolean).sort()[0];
  const last = [project.end_date, ...ends].filter(Boolean).sort().at(-1);
  const span = Math.max(toTime(last) - toTime(first) + DAY, DAY);
  const pos = (iso) => ((toTime(iso) - toTime(first)) / span) * 100;
  const months = [];
  for (let m = `${first.slice(0, 7)}-01`; m <= last; m = addDays(m, 32).slice(0, 7) + '-01') {
    if (m >= first) months.push(m);
  }
  const now = today();
  return (
    <div className="timeline-scroll">
      <div className="timeline" role="list" aria-label="Deliverable timeline">
        <div className="timeline-axis" aria-hidden="true">
          {months.map((m) => <span key={m} style={{ left: `${pos(m)}%` }}>{formatShortDate(m)}</span>)}
          {now >= first && now <= last && <span className="timeline-today" style={{ left: `${pos(now)}%` }}>Today</span>}
        </div>
        {items.map((d) => {
          const start = d.start_date || d.due_date;
          const end = d.due_date || d.start_date;
          return (
            <div key={d.id} className="timeline-row" role="listitem">
              <span className="timeline-label" title={d.title}>{d.title}</span>
              <span className="timeline-lane">
                {start ? (
                  <span
                    className={`timeline-bar status-${d.status} ${d.is_overdue ? 'overdue' : ''}`}
                    style={{ left: `${pos(start)}%`, width: `max(${pos(addDays(end, 1)) - pos(start)}%, 6px)` }}
                    title={`${d.title}: ${formatDate(d.start_date)} – ${formatDate(d.due_date)} · ${label(d.status)} · ${d.progress_pct}%`}
                  >
                    <span className="timeline-progress" style={{ width: `${d.progress_pct}%` }} />
                  </span>
                ) : <span className="muted">No dates</span>}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Deliverables for one project: list or timeline, with dependencies and archiving.
 *
 * @param {{project: object, members: object[], canManage: boolean, onChanged: Function}} props
 */
export default function DeliverablesTab({ project, members, canManage, onChanged }) {
  const [view, setView] = useState('list');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [archived, setArchived] = useState('false');
  const [sort, setSort] = useState('due_date');
  const [editing, setEditing] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const [confirmState, setConfirmState] = useState({ busy: false, error: '' });
  const q = useDebouncedValue(search);

  const query = { project_id: project.id, q, status, archived, sort, page_size: 100 };
  const { data, error, loading, reload } = useAsync(() => deliverablesApi.list(query), JSON.stringify(query));
  const { data: all, reload: reloadAll } = useAsync(
    () => deliverablesApi.list({ project_id: project.id, page_size: 100, sort: 'title' }),
    `all-deliverables-${project.id}`,
  );
  const titles = Object.fromEntries((all?.items || []).map((d) => [d.id, d.title]));

  const assignees = [
    ...(project.manager_id ? [{ id: project.manager_id, name: `${project.manager_name} (manager)` }] : []),
    ...[...new Map(members.filter((m) => m.user_id !== project.manager_id).map((m) => [m.user_id, m])).values()]
      .map((m) => ({ id: m.user_id, name: m.full_name })),
  ];

  const changed = () => { reload(); reloadAll(); onChanged(); };

  const save = async (body) => {
    if (editing === 'new') await deliverablesApi.create(body);
    else await deliverablesApi.update(editing.id, body);
    setEditing(null);
    changed();
  };

  const runConfirm = async () => {
    setConfirmState({ busy: true, error: '' });
    try {
      if (confirm.action === 'archive') await deliverablesApi.archive(confirm.row.id);
      else await deliverablesApi.reactivate(confirm.row.id);
      setConfirm(null);
      setConfirmState({ busy: false, error: '' });
      changed();
    } catch (err) {
      setConfirmState({ busy: false, error: err.message });
    }
  };

  const columns = [
    {
      key: 'title',
      label: 'Deliverable',
      sortKey: 'title',
      render: (d) => (
        <div className="cell-title">
          <strong>{d.title}</strong>
          {d.depends_on.length > 0 && (
            <span className="muted clamp">Depends on: {d.depends_on.map((id) => titles[id] || `#${id}`).join(', ')}</span>
          )}
        </div>
      ),
    },
    { key: 'assignee_name', label: 'Assignee', render: (d) => d.assignee_name || 'Unassigned' },
    {
      key: 'status',
      label: 'Status',
      sortKey: 'status',
      render: (d) => (
        <span className="badge-row">
          <Badge value={d.is_archived ? 'archived' : d.status} text={d.is_archived ? 'Archived' : undefined} />
          {d.is_blocked && !d.is_archived && d.status !== 'done' && <Badge value="blocked" text="Waiting" />}
        </span>
      ),
    },
    {
      key: 'due_date',
      label: 'Due',
      sortKey: 'due_date',
      render: (d) => <span className={d.is_overdue ? 'due overdue' : 'due'}>{formatDate(d.due_date)}{d.is_overdue ? ' · overdue' : ''}</span>,
    },
    {
      key: 'progress_pct',
      label: 'Progress',
      sortKey: 'progress_pct',
      render: (d) => (
        <div className="progress-cell">
          <div className="progress-track"><div className="progress-fill" style={{ width: `${d.progress_pct}%` }} /></div>
          <span className="muted">{d.progress_pct}%</span>
        </div>
      ),
    },
  ];
  if (canManage) {
    columns.push({
      key: 'actions',
      label: 'Actions',
      className: 'actions-cell',
      render: (d) => (
        <div className="row-actions">
          {d.is_archived ? (
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirm({ row: d, action: 'reactivate' })}>Restore</button>
          ) : (
            <>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(d)}>Edit</button>
              <button type="button" className="btn btn-ghost btn-sm text-danger" onClick={() => setConfirm({ row: d, action: 'archive' })}>Archive</button>
            </>
          )}
        </div>
      ),
    });
  }

  return (
    <div className="tab-panel">
      <Card
        title="Deliverables"
        actions={(
          <>
            <div className="segmented" role="group" aria-label="View">
              <button type="button" className={view === 'list' ? 'active' : ''} aria-pressed={view === 'list'} onClick={() => setView('list')}>List</button>
              <button type="button" className={view === 'timeline' ? 'active' : ''} aria-pressed={view === 'timeline'} onClick={() => setView('timeline')}>Timeline</button>
            </div>
            {canManage && <button type="button" className="btn btn-primary btn-sm" onClick={() => setEditing('new')}>New deliverable</button>}
          </>
        )}
      >
        <FilterBar>
          <input type="search" className="search-input" placeholder="Search deliverables…" aria-label="Search deliverables"
            value={search} onChange={(e) => setSearch(e.target.value)} />
          <select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {DELIVERABLE_STATUSES.map((s) => <option key={s} value={s}>{label(s)}</option>)}
          </select>
          <select aria-label="Archived deliverables" value={archived} onChange={(e) => setArchived(e.target.value)}>
            <option value="false">Current</option>
            <option value="true">Archived</option>
            <option value="all">All</option>
          </select>
        </FilterBar>
        {error && <ErrorState error={error} onRetry={reload} />}
        {loading && !data && <Loading />}
        {data && view === 'list' && (
          <DataTable caption="Deliverables" columns={columns} rows={data.items} sort={sort} onSort={setSort}
            empty={<EmptyState title={q || status ? 'No deliverables match' : 'No deliverables yet'} />} />
        )}
        {data && view === 'timeline' && <Timeline items={data.items} project={project} />}
      </Card>

      {editing && (
        <DeliverableForm
          project={project}
          deliverable={editing === 'new' ? null : editing}
          assignees={assignees}
          others={all?.items || []}
          onClose={() => setEditing(null)}
          onSave={save}
        />
      )}
      {confirm && (
        <ConfirmDialog
          title={confirm.action === 'archive' ? 'Archive deliverable?' : 'Restore deliverable?'}
          message={confirm.action === 'archive'
            ? <>Archive <strong>{confirm.row.title}</strong>? It is kept for history and stops blocking anything that depends on it.</>
            : <>Restore <strong>{confirm.row.title}</strong>?</>}
          confirmLabel={confirm.action === 'archive' ? 'Archive' : 'Restore'}
          danger={confirm.action === 'archive'}
          busy={confirmState.busy}
          error={confirmState.error}
          onConfirm={runConfirm}
          onCancel={() => { setConfirm(null); setConfirmState({ busy: false, error: '' }); }}
        />
      )}
    </div>
  );
}
