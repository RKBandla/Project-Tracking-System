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
import { formatDate, label } from '../../utils/format';

/**
 * Deliverables for one project with search and status filter.
 *
 * @param {{project: object, members: object[], canManage: boolean, onChanged: Function}} props
 */
export default function DeliverablesTab({ project, members, canManage, onChanged }) {
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [sort, setSort] = useState('due_date');
  const [editing, setEditing] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [deleteState, setDeleteState] = useState({ busy: false, error: '' });
  const q = useDebouncedValue(search);

  const query = { project_id: project.id, q, status, sort, page_size: 100 };
  const { data, error, loading, reload } = useAsync(() => deliverablesApi.list(query), JSON.stringify(query));

  const assignees = [
    ...(project.manager_id ? [{ id: project.manager_id, name: `${project.manager_name} (manager)` }] : []),
    ...members.filter((m) => m.user_id !== project.manager_id).map((m) => ({ id: m.user_id, name: m.full_name })),
  ];

  const changed = () => { reload(); onChanged(); };

  const save = async (body) => {
    if (editing === 'new') await deliverablesApi.create(body);
    else await deliverablesApi.update(editing.id, body);
    setEditing(null);
    changed();
  };

  const remove = async () => {
    setDeleteState({ busy: true, error: '' });
    try {
      await deliverablesApi.remove(deleting.id);
      setDeleting(null);
      setDeleteState({ busy: false, error: '' });
      changed();
    } catch (err) {
      setDeleteState({ busy: false, error: err.message });
    }
  };

  const columns = [
    {
      key: 'title',
      label: 'Deliverable',
      sortKey: 'title',
      render: (d) => (
        <div className="cell-title"><strong>{d.title}</strong>{d.description && <span className="muted clamp">{d.description}</span>}</div>
      ),
    },
    { key: 'assignee_name', label: 'Assignee', render: (d) => d.assignee_name || 'Unassigned' },
    { key: 'status', label: 'Status', sortKey: 'status', render: (d) => <Badge value={d.status} /> },
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
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(d)}>Edit</button>
          <button type="button" className="btn btn-ghost btn-sm text-danger" onClick={() => setDeleting(d)}>Delete</button>
        </div>
      ),
    });
  }

  return (
    <div className="tab-panel">
      <Card
        title="Deliverables"
        actions={canManage && (
          <button type="button" className="btn btn-primary btn-sm" onClick={() => setEditing('new')}>New deliverable</button>
        )}
      >
        <FilterBar>
          <input type="search" className="search-input" placeholder="Search deliverables…" aria-label="Search deliverables"
            value={search} onChange={(e) => setSearch(e.target.value)} />
          <select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {DELIVERABLE_STATUSES.map((s) => <option key={s} value={s}>{label(s)}</option>)}
          </select>
        </FilterBar>
        {error && <ErrorState error={error} onRetry={reload} />}
        {loading && !data && <Loading />}
        {data && (
          <DataTable
            caption="Deliverables"
            columns={columns}
            rows={data.items}
            sort={sort}
            onSort={setSort}
            empty={<EmptyState title={q || status ? 'No deliverables match' : 'No deliverables yet'} />}
          />
        )}
      </Card>

      {editing && (
        <DeliverableForm
          project={project}
          deliverable={editing === 'new' ? null : editing}
          assignees={assignees}
          onClose={() => setEditing(null)}
          onSave={save}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title="Delete deliverable?"
          message={<>Delete <strong>{deleting.title}</strong>? This cannot be undone.</>}
          confirmLabel="Delete"
          danger
          busy={deleteState.busy}
          error={deleteState.error}
          onConfirm={remove}
          onCancel={() => { setDeleting(null); setDeleteState({ busy: false, error: '' }); }}
        />
      )}
    </div>
  );
}
