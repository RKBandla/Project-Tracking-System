import { usersApi } from '../../api/services';
import { MAX_WEEKLY_HOURS } from '../../auth/permissions';
import { useAsync } from '../../hooks/useAsync';
import { toNumber, useForm } from '../../hooks/useForm';
import { Alert } from '../Feedback';
import FormField from '../FormField';
import HoursBar from '../HoursBar';
import { Modal } from '../Modal';

/**
 * Assign a person to a project, or change their hours/role. Shows the
 * person's current weekly load so the 40-hour limit is visible up front.
 *
 * @param {{project: object, assignment?: object, excludeUserIds?: number[],
 *          onSave: Function, onClose: Function}} props
 */
export default function AssignmentForm({ project, assignment, excludeUserIds = [], onSave, onClose }) {
  const editing = Boolean(assignment);
  const { data: people, loading: peopleLoading } = useAsync(
    () => (editing ? Promise.resolve(null) : usersApi.list({ is_active: 'true', page_size: 100, sort: 'name' })),
    `assignable-${editing}`,
  );
  const candidates = (people?.items || [])
    .filter((p) => p.role !== 'admin' && !excludeUserIds.includes(p.id));

  const { values, bind, errors, formError, busy, handleSubmit } = useForm({
    user_id: assignment?.user_id ?? '',
    hours_per_week: assignment?.hours_per_week ?? 8,
    project_role: assignment?.project_role || '',
  });

  const userId = toNumber(values.user_id);
  const { data: workload } = useAsync(
    () => (userId ? usersApi.workload(userId) : Promise.resolve(null)),
    `workload-${userId}`,
  );
  const currentHere = editing ? assignment.hours_per_week : 0;
  const available = workload ? workload.remaining_hours + currentHere : null;
  const requested = toNumber(values.hours_per_week) || 0;
  const overLimit = available !== null && requested > available;

  const submit = handleSubmit(async (v) => {
    const body = { hours_per_week: toNumber(v.hours_per_week), project_role: v.project_role };
    if (!editing) {
      body.project_id = project.id;
      body.user_id = toNumber(v.user_id);
    }
    await onSave(body);
  });

  return (
    <Modal
      title={editing ? `Edit ${assignment.full_name}` : `Assign to ${project.name}`}
      onClose={onClose}
      footer={(
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button type="submit" form="assignment-form" className="btn btn-primary" disabled={busy || overLimit}>
            {busy ? 'Saving…' : editing ? 'Save' : 'Assign'}
          </button>
        </>
      )}
    >
      <form id="assignment-form" className="form-stack" onSubmit={submit} noValidate>
        {formError && <Alert kind="error">{formError}</Alert>}
        {!editing && (
          <FormField
            label="Person"
            required
            error={errors.user_id}
            hint={!peopleLoading && !candidates.length ? 'Everyone available is already on this project.' : undefined}
          >
            <select {...bind('user_id')}>
              <option value="">{peopleLoading ? 'Loading…' : 'Select a person'}</option>
              {candidates.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.full_name} · {p.job_title} ({p.allocated_hours}/{MAX_WEEKLY_HOURS} h)
                </option>
              ))}
            </select>
          </FormField>
        )}
        {workload && (
          <div className="workload-preview">
            <span className="muted">Current weekly load</span>
            <HoursBar hours={workload.allocated_hours} />
            <span className={overLimit ? 'text-danger' : 'muted'}>
              {available} h available for this project{overLimit ? ' — reduce the hours to stay within 40' : ''}
            </span>
          </div>
        )}
        <FormField label="Hours per week" required error={errors.hours_per_week} hint="Between 1 and 40 hours">
          <input type="number" min="1" max={MAX_WEEKLY_HOURS} step="1" inputMode="numeric" {...bind('hours_per_week')} />
        </FormField>
        <FormField label="Role on project" error={errors.project_role}>
          <input {...bind('project_role')} maxLength={100} placeholder="e.g. Developer, QA, Analyst" />
        </FormField>
      </form>
    </Modal>
  );
}
