import { useState } from 'react';
import { assignmentsApi } from '../../api/services';
import Badge from '../../components/Badge';
import { DataTable } from '../../components/DataTable';
import { EmptyState, ErrorState, Loading } from '../../components/Feedback';
import AssignmentForm from '../../components/forms/AssignmentForm';
import { ConfirmDialog } from '../../components/Modal';
import { Card, FilterBar } from '../../components/PageParts';
import { useAsync } from '../../hooks/useAsync';
import { formatCents, formatDate } from '../../utils/format';

/**
 * People booked on a project: hours per week over a date range. Admins and the
 * project's manager book anyone, change bookings and end them (archive).
 *
 * @param {{project: object, canManage: boolean, showCost: boolean, onChanged: Function}} props
 */
export default function ResourcesTab({ project, canManage, showCost, onChanged }) {
  const [archived, setArchived] = useState('false');
  const [editing, setEditing] = useState(null); // null | 'new' | assignment
  const [confirm, setConfirm] = useState(null); // {row, action}
  const [confirmState, setConfirmState] = useState({ busy: false, error: '' });

  const query = { project_id: project.id, archived, page_size: 100, sort: 'start_date' };
  const { data, error, loading, reload } = useAsync(() => assignmentsApi.list(query), JSON.stringify(query));

  const changed = () => { reload(); onChanged(); };

  const save = async (body) => {
    if (editing === 'new') await assignmentsApi.create(body);
    else await assignmentsApi.update(editing.id, body);
    setEditing(null);
    changed();
  };

  const runConfirm = async () => {
    setConfirmState({ busy: true, error: '' });
    try {
      if (confirm.action === 'archive') await assignmentsApi.archive(confirm.row.id);
      else await assignmentsApi.reactivate(confirm.row.id);
      setConfirm(null);
      setConfirmState({ busy: false, error: '' });
      changed();
    } catch (err) {
      setConfirmState({ busy: false, error: err.message });
    }
  };

  const columns = [
    {
      key: 'full_name',
      label: 'Person',
      sortKey: 'full_name',
      render: (a) => (
        <div className="cell-title"><strong>{a.full_name}</strong><span className="muted">{a.employee_id} · {a.project_role || a.job_title}</span></div>
      ),
    },
    { key: 'hours_per_week', label: 'Hours / week', render: (a) => `${a.hours_per_week} h` },
    { key: 'dates', label: 'Booked', render: (a) => `${formatDate(a.start_date)} – ${formatDate(a.end_date)}` },
    ...(showCost ? [{ key: 'planned_cents', label: 'Planned cost', className: 'num', render: (a) => formatCents(a.planned_cents) }] : []),
    ...(archived !== 'false' ? [{ key: 'state', label: 'State', render: (a) => <Badge value={a.is_archived ? 'archived' : 'active'} text={a.is_archived ? 'Ended' : 'Active'} /> }] : []),
  ];
  if (canManage) {
    columns.push({
      key: 'actions',
      label: 'Actions',
      className: 'actions-cell',
      render: (a) => (
        <div className="row-actions">
          {a.is_archived ? (
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirm({ row: a, action: 'reactivate' })}>Restore</button>
          ) : (
            <>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(a)}>Edit</button>
              <button type="button" className="btn btn-ghost btn-sm text-danger" onClick={() => setConfirm({ row: a, action: 'archive' })}>End booking</button>
            </>
          )}
        </div>
      ),
    });
  }

  return (
    <div className="tab-panel">
      <Card
        title="Resources"
        actions={canManage && <button type="button" className="btn btn-primary btn-sm" onClick={() => setEditing('new')}>Book someone</button>}
      >
        <FilterBar>
          <select aria-label="Show bookings" value={archived} onChange={(e) => setArchived(e.target.value)}>
            <option value="false">Active bookings</option>
            <option value="true">Ended bookings</option>
            <option value="all">All bookings</option>
          </select>
        </FilterBar>
        {error && <ErrorState error={error} onRetry={reload} />}
        {loading && !data && <Loading />}
        {data && (
          <DataTable caption="Resources" columns={columns} rows={data.items}
            empty={<EmptyState title="Nobody is booked yet">{canManage && 'Book people to plan capacity and cost.'}</EmptyState>} />
        )}
      </Card>

      {editing && (
        <AssignmentForm project={project} assignment={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)} onSave={save} />
      )}
      {confirm && (
        <ConfirmDialog
          title={confirm.action === 'archive' ? 'End this booking?' : 'Restore this booking?'}
          message={confirm.action === 'archive'
            ? <>End <strong>{confirm.row.full_name}</strong>&apos;s booking on {project.name}? The record is kept for cost history.</>
            : <>Restore <strong>{confirm.row.full_name}</strong>&apos;s booking? It must still fit within 40 hours a week.</>}
          confirmLabel={confirm.action === 'archive' ? 'End booking' : 'Restore'}
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
