import { emptyToNull, toNumber, useForm } from '../../hooks/useForm';
import { DELIVERABLE_STATUSES as STATUSES } from '../../utils/constants';
import { label } from '../../utils/format';
import { Alert } from '../Feedback';
import FormField from '../FormField';
import { Modal } from '../Modal';

/**
 * Create or edit a deliverable. Assignees are limited to the project team and its manager.
 *
 * @param {{project: object, deliverable?: object, assignees: {id: number, name: string}[],
 *          onSave: Function, onClose: Function}} props
 */
export default function DeliverableForm({ project, deliverable, assignees, onSave, onClose }) {
  const { values, bind, setValue, errors, formError, busy, handleSubmit } = useForm({
    title: deliverable?.title || '',
    description: deliverable?.description || '',
    status: deliverable?.status || 'todo',
    due_date: deliverable?.due_date || '',
    assignee_id: deliverable?.assignee_id ?? '',
    progress_pct: deliverable?.progress_pct ?? 0,
  });

  const submit = handleSubmit(async (v) => {
    const body = {
      title: v.title,
      description: v.description,
      status: v.status,
      due_date: emptyToNull(v.due_date),
      assignee_id: toNumber(v.assignee_id),
      progress_pct: toNumber(v.progress_pct) ?? 0,
    };
    if (!deliverable) body.project_id = project.id;
    await onSave(body);
  });

  const onStatus = (event) => {
    setValue('status', event.target.value);
    if (event.target.value === 'done') setValue('progress_pct', 100);
  };

  return (
    <Modal
      title={deliverable ? 'Edit deliverable' : 'New deliverable'}
      onClose={onClose}
      footer={(
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button type="submit" form="deliverable-form" className="btn btn-primary" disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </button>
        </>
      )}
    >
      <form id="deliverable-form" className="form-grid" onSubmit={submit} noValidate>
        {formError && <div className="span-all"><Alert kind="error">{formError}</Alert></div>}
        <FormField label="Title" required error={errors.title} className="span-all">
          <input {...bind('title')} maxLength={200} />
        </FormField>
        <FormField label="Description" error={errors.description} className="span-all">
          <textarea {...bind('description')} rows={3} />
        </FormField>
        <FormField label="Status" error={errors.status}>
          <select {...bind('status')} onChange={onStatus}>
            {STATUSES.map((s) => <option key={s} value={s}>{label(s)}</option>)}
          </select>
        </FormField>
        <FormField label="Due date" error={errors.due_date}>
          <input type="date" {...bind('due_date')} />
        </FormField>
        <FormField label="Assignee" error={errors.assignee_id}>
          <select {...bind('assignee_id')}>
            <option value="">Unassigned</option>
            {assignees.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </FormField>
        <FormField label={`Progress (${values.progress_pct || 0}%)`} error={errors.progress_pct}>
          <input type="range" min="0" max="100" step="5" {...bind('progress_pct')} />
        </FormField>
      </form>
    </Modal>
  );
}
