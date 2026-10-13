import { useState } from 'react';
import { assignmentsApi } from '../../api/services';
import { DataTable } from '../../components/DataTable';
import { EmptyState } from '../../components/Feedback';
import AssignmentForm from '../../components/forms/AssignmentForm';
import { ConfirmDialog } from '../../components/Modal';
import { Card } from '../../components/PageParts';

/**
 * Project team with weekly hours. Admins and the project manager can assign
 * people (managers: only their direct reports), change hours and remove people.
 *
 * @param {{project: object, members: object[], canManage: boolean, onChanged: Function}} props
 */
export default function TeamTab({ project, members, canManage, onChanged }) {
  const [editing, setEditing] = useState(null); // null | 'new' | member
  const [removing, setRemoving] = useState(null);
  const [removeState, setRemoveState] = useState({ busy: false, error: '' });

  const save = async (body) => {
    if (editing === 'new') await assignmentsApi.create(body);
    else await assignmentsApi.update(editing.id, body);
    setEditing(null);
    onChanged();
  };

  const remove = async () => {
    setRemoveState({ busy: true, error: '' });
    try {
      await assignmentsApi.remove(removing.id);
      setRemoving(null);
      setRemoveState({ busy: false, error: '' });
      onChanged();
    } catch (err) {
      setRemoveState({ busy: false, error: err.message });
    }
  };

  const columns = [
    {
      key: 'full_name',
      label: 'Name',
      render: (m) => (
        <div className="cell-title"><strong>{m.full_name}</strong><span className="muted">{m.employee_id} · {m.job_title}</span></div>
      ),
    },
    { key: 'project_role', label: 'Project role', render: (m) => m.project_role || '—' },
    { key: 'hours_per_week', label: 'Hours / week', render: (m) => `${m.hours_per_week} h` },
  ];
  if (canManage) {
    columns.push({
      key: 'actions',
      label: 'Actions',
      className: 'actions-cell',
      render: (m) => (
        <div className="row-actions">
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(m)}>Edit</button>
          <button type="button" className="btn btn-ghost btn-sm text-danger" onClick={() => setRemoving(m)}>Remove</button>
        </div>
      ),
    });
  }

  const totalHours = members.reduce((sum, m) => sum + m.hours_per_week, 0);

  return (
    <div className="tab-panel">
      <Card
        title={`Team · ${members.length} ${members.length === 1 ? 'person' : 'people'} · ${totalHours} h/week`}
        actions={canManage && (
          <button type="button" className="btn btn-primary btn-sm" onClick={() => setEditing('new')}>Assign person</button>
        )}
      >
        <DataTable
          caption="Project team"
          columns={columns}
          rows={members}
          empty={<EmptyState title="No one is assigned yet">{canManage && 'Assign people to start tracking capacity.'}</EmptyState>}
        />
      </Card>

      {editing && (
        <AssignmentForm
          project={project}
          assignment={editing === 'new' ? null : editing}
          excludeUserIds={members.map((m) => m.user_id)}
          onClose={() => setEditing(null)}
          onSave={save}
        />
      )}
      {removing && (
        <ConfirmDialog
          title="Remove from project?"
          message={<>Remove <strong>{removing.full_name}</strong> from {project.name}? Their open deliverables on this project will become unassigned.</>}
          confirmLabel="Remove"
          danger
          busy={removeState.busy}
          error={removeState.error}
          onConfirm={remove}
          onCancel={() => { setRemoving(null); setRemoveState({ busy: false, error: '' }); }}
        />
      )}
    </div>
  );
}
