import { emptyToNull, useForm } from '../../hooks/useForm';
import { centsToDollars, dollarsToCents } from '../../utils/format';
import { Alert } from '../Feedback';
import FormField from '../FormField';
import { Modal } from '../Modal';

/**
 * Manager's request asking an admin to create a project.
 *
 * @param {{request?: object, onSave: Function, onClose: Function}} props
 */
export default function RequestForm({ request, onSave, onClose }) {
  const { bind, errors, formError, busy, handleSubmit } = useForm({
    name: request?.name || '',
    description: request?.description || '',
    justification: request?.justification || '',
    proposed_start_date: request?.proposed_start_date || '',
    proposed_end_date: request?.proposed_end_date || '',
    proposed_budget: centsToDollars(request?.proposed_budget_cents ?? null),
  });

  const submit = handleSubmit(async (v) => {
    await onSave({
      name: v.name,
      description: v.description,
      justification: v.justification,
      proposed_start_date: emptyToNull(v.proposed_start_date),
      proposed_end_date: emptyToNull(v.proposed_end_date),
      proposed_budget_cents: dollarsToCents(v.proposed_budget) ?? 0,
    });
  });

  return (
    <Modal
      title={request ? 'Edit project request' : 'Request a new project'}
      onClose={onClose}
      size="lg"
      footer={(
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button type="submit" form="request-form" className="btn btn-primary" disabled={busy}>
            {busy ? 'Submitting…' : request ? 'Save' : 'Submit request'}
          </button>
        </>
      )}
    >
      <form id="request-form" className="form-grid" onSubmit={submit} noValidate>
        {!request && (
          <p className="muted span-all">An admin will review your request. Once approved, the project is created with you as its manager.</p>
        )}
        {formError && <div className="span-all"><Alert kind="error">{formError}</Alert></div>}
        <FormField label="Project name" required error={errors.name} className="span-all">
          <input {...bind('name')} maxLength={200} />
        </FormField>
        <FormField label="Description" error={errors.description} className="span-all">
          <textarea {...bind('description')} rows={3} />
        </FormField>
        <FormField label="Business justification" error={errors.justification} className="span-all">
          <textarea {...bind('justification')} rows={3} />
        </FormField>
        <FormField label="Proposed start" error={errors.proposed_start_date}>
          <input type="date" {...bind('proposed_start_date')} />
        </FormField>
        <FormField label="Proposed end" error={errors.proposed_end_date}>
          <input type="date" {...bind('proposed_end_date')} />
        </FormField>
        <FormField label="Proposed budget (USD)" error={errors.proposed_budget_cents}>
          <input type="number" min="0" step="0.01" inputMode="decimal" {...bind('proposed_budget')} />
        </FormField>
      </form>
    </Modal>
  );
}
