import { usersApi } from '../../api/services';
import { useAuth } from '../../auth/useAuth';
import { can } from '../../auth/permissions';
import { useAsync } from '../../hooks/useAsync';
import { emptyToNull, toNumber, useForm } from '../../hooks/useForm';
import { PROJECT_STATUSES } from '../../utils/constants';
import { centsToDollars, dollarsToCents, label } from '../../utils/format';
import { Alert } from '../Feedback';
import FormField from '../FormField';
import { Modal } from '../Modal';

/**
 * Create or edit a project. Admins edit every field; a project's manager edits
 * only its description and status.
 *
 * @param {{project?: object, onSave: Function, onClose: Function}} props
 */
export default function ProjectForm({ project, onSave, onClose }) {
  const { user } = useAuth();
  const full = can(user, 'projects:editAll');
  const { data: people } = useAsync(
    () => (full ? usersApi.list({ is_active: 'true', page_size: 100, sort: 'name' }) : Promise.resolve(null)),
    `managers-${full}`,
  );
  const managers = (people?.items || []).filter((p) => p.role !== 'employee');

  const { bind, errors, formError, busy, handleSubmit } = useForm({
    name: project?.name || '',
    description: project?.description || '',
    status: project?.status || 'planned',
    start_date: project?.start_date || '',
    end_date: project?.end_date || '',
    budget: centsToDollars(project?.budget_cents ?? null),
    manager_id: project?.manager_id ?? '',
  });

  const submit = handleSubmit(async (values) => {
    const body = { description: values.description, status: values.status };
    if (full) {
      Object.assign(body, {
        name: values.name,
        start_date: emptyToNull(values.start_date),
        end_date: emptyToNull(values.end_date),
        budget_cents: dollarsToCents(values.budget) ?? 0,
        manager_id: toNumber(values.manager_id),
      });
    }
    await onSave(body);
  });

  return (
    <Modal
      title={project ? `Edit ${project.code}` : 'New project'}
      onClose={onClose}
      size="lg"
      footer={(
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button type="submit" form="project-form" className="btn btn-primary" disabled={busy}>
            {busy ? 'Saving…' : project ? 'Save changes' : 'Create project'}
          </button>
        </>
      )}
    >
      <form id="project-form" className="form-grid" onSubmit={submit} noValidate>
        {!full && <p className="muted span-all">As the project's manager you can change its description and status.</p>}
        {formError && <div className="span-all"><Alert kind="error">{formError}</Alert></div>}
        {full && (
          <FormField label="Name" required error={errors.name} className="span-all">
            <input {...bind('name')} maxLength={200} />
          </FormField>
        )}
        <FormField label="Description" error={errors.description} className="span-all">
          <textarea {...bind('description')} rows={3} />
        </FormField>
        <FormField label="Status" error={errors.status}>
          <select {...bind('status')}>
            {PROJECT_STATUSES.map((s) => <option key={s} value={s}>{label(s)}</option>)}
          </select>
        </FormField>
        {full && (
          <>
            <FormField label="Project manager" error={errors.manager_id}>
              <select {...bind('manager_id')}>
                <option value="">Unassigned</option>
                {managers.map((m) => <option key={m.id} value={m.id}>{m.full_name} ({label(m.role)})</option>)}
              </select>
            </FormField>
            <FormField label="Start date" error={errors.start_date}>
              <input type="date" {...bind('start_date')} />
            </FormField>
            <FormField label="End date" error={errors.end_date}>
              <input type="date" {...bind('end_date')} />
            </FormField>
            <FormField label="Budget (USD)" error={errors.budget_cents} hint="Stored in whole cents">
              <input type="number" min="0" step="0.01" inputMode="decimal" {...bind('budget')} />
            </FormField>
          </>
        )}
      </form>
    </Modal>
  );
}
