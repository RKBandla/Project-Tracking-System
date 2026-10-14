import { emptyToNull, toNumber, useForm } from '../../hooks/useForm';
import { DELIVERABLE_STATUSES } from '../../utils/constants';
import { label } from '../../utils/format';
import { Alert } from '../Feedback';
import FormField from '../FormField';
import MilestoneMark from '../MilestoneMark';
import { Modal } from '../Modal';

/**
 * Create or edit a deliverable, including what it depends on. The server refuses
 * links that would form a loop and "done" while a dependency is unfinished.
 * A milestone is a checkpoint with a single date, so it has no start date.
 *
 * @param {{project: object, deliverable?: object, assignees: {id: number, name: string}[],
 *          others: object[], onSave: Function, onClose: Function}} props
 */
export default function DeliverableForm({ project, deliverable, assignees, others, onSave, onClose }) {
  const { values, bind, setValue, errors, formError, busy, handleSubmit } = useForm({
    title: deliverable?.title || '',
    description: deliverable?.description || '',
    status: deliverable?.status || 'todo',
    start_date: deliverable?.start_date || '',
    due_date: deliverable?.due_date || '',
    assignee_id: deliverable?.assignee_id ?? '',
    progress_pct: deliverable?.progress_pct ?? 0,
    depends_on: deliverable?.depends_on || [],
    is_milestone: deliverable?.is_milestone ?? false,
  });
  const candidates = others.filter((d) => d.id !== deliverable?.id);

  const submit = handleSubmit(async (v) => {
    const body = {
      title: v.title,
      description: v.description,
      status: v.status,
      start_date: v.is_milestone ? null : emptyToNull(v.start_date),
      due_date: emptyToNull(v.due_date),
      assignee_id: toNumber(v.assignee_id),
      progress_pct: toNumber(v.progress_pct) ?? 0,
      depends_on: v.depends_on,
      is_milestone: Boolean(v.is_milestone),
    };
    if (!deliverable) body.project_id = project.id;
    await onSave(body);
  });

  const onStatus = (event) => {
    setValue('status', event.target.value);
    if (event.target.value === 'done') setValue('progress_pct', 100);
  };
  const toggleDependency = (id) => setValue(
    'depends_on',
    values.depends_on.includes(id) ? values.depends_on.filter((d) => d !== id) : [...values.depends_on, id],
  );

  return (
    <Modal
      title={deliverable ? `Edit ${deliverable.is_milestone ? 'milestone' : 'deliverable'}` : 'New deliverable'}
      onClose={onClose}
      size="lg"
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
          <textarea {...bind('description')} rows={2} />
        </FormField>
        <div className="field checkbox-field span-all">
          <label>
            <input type="checkbox" checked={Boolean(values.is_milestone)}
              onChange={(e) => setValue('is_milestone', e.target.checked)} />
            <MilestoneMark /> Milestone
          </label>
          <p className="field-hint">A key checkpoint with one date, such as “Design approved” or “Go-live”.</p>
        </div>
        <FormField label="Status" error={errors.status}>
          <select {...bind('status')} onChange={onStatus}>
            {DELIVERABLE_STATUSES.map((s) => <option key={s} value={s}>{label(s)}</option>)}
          </select>
        </FormField>
        <FormField label="Assignee" error={errors.assignee_id}>
          <select {...bind('assignee_id')}>
            <option value="">Unassigned</option>
            {assignees.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </FormField>
        {!values.is_milestone && (
          <FormField label="Start date" error={errors.start_date}>
            <input type="date" {...bind('start_date')} />
          </FormField>
        )}
        <FormField label={values.is_milestone ? 'Milestone date' : 'Due date'} required={Boolean(values.is_milestone)}
          error={errors.due_date || (values.is_milestone ? errors.start_date : undefined)}>
          <input type="date" {...bind('due_date')} />
        </FormField>
        <FormField label={`Progress (${values.progress_pct || 0}%)`} error={errors.progress_pct} className="span-all">
          <input type="range" min="0" max="100" step="5" {...bind('progress_pct')} />
        </FormField>
        <fieldset className="span-all checkbox-group">
          <legend>Depends on</legend>
          {candidates.length === 0 && <p className="muted">No other deliverables on this project yet.</p>}
          {candidates.map((d) => (
            <label key={d.id}>
              <input type="checkbox" checked={values.depends_on.includes(d.id)} onChange={() => toggleDependency(d.id)} />
              {d.title} <span className="muted">({label(d.status)})</span>
            </label>
          ))}
          {errors.depends_on && <p className="field-error">{errors.depends_on}</p>}
        </fieldset>
      </form>
    </Modal>
  );
}
