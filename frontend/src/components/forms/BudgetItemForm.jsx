import { toNumber, useForm } from '../../hooks/useForm';
import { BUDGET_CATEGORIES } from '../../utils/constants';
import { label, today } from '../../utils/format';
import { Alert } from '../Feedback';
import FormField from '../FormField';
import { Modal } from '../Modal';

/**
 * Create or edit a budget line item.
 *
 * @param {{project: object, item?: object, onSave: Function, onClose: Function}} props
 */
export default function BudgetItemForm({ project, item, onSave, onClose }) {
  const { bind, errors, formError, busy, handleSubmit } = useForm({
    category: item?.category || 'labor',
    description: item?.description || '',
    planned_amount: item?.planned_amount ?? '',
    actual_amount: item?.actual_amount ?? '',
    entry_date: item?.entry_date || today(),
  });

  const submit = handleSubmit(async (v) => {
    const body = {
      category: v.category,
      description: v.description,
      planned_amount: toNumber(v.planned_amount) ?? 0,
      actual_amount: toNumber(v.actual_amount) ?? 0,
      entry_date: v.entry_date || today(),
    };
    if (!item) body.project_id = project.id;
    await onSave(body);
  });

  return (
    <Modal
      title={item ? 'Edit budget item' : 'New budget item'}
      onClose={onClose}
      footer={(
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button type="submit" form="budget-form" className="btn btn-primary" disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </button>
        </>
      )}
    >
      <form id="budget-form" className="form-grid" onSubmit={submit} noValidate>
        {formError && <div className="span-all"><Alert kind="error">{formError}</Alert></div>}
        <FormField label="Description" required error={errors.description} className="span-all">
          <input {...bind('description')} maxLength={255} />
        </FormField>
        <FormField label="Category" error={errors.category}>
          <select {...bind('category')}>
            {BUDGET_CATEGORIES.map((c) => <option key={c} value={c}>{label(c)}</option>)}
          </select>
        </FormField>
        <FormField label="Date" error={errors.entry_date}>
          <input type="date" {...bind('entry_date')} />
        </FormField>
        <FormField label="Planned (USD)" error={errors.planned_amount}>
          <input type="number" min="0" step="0.01" inputMode="decimal" {...bind('planned_amount')} />
        </FormField>
        <FormField label="Actual (USD)" error={errors.actual_amount}>
          <input type="number" min="0" step="0.01" inputMode="decimal" {...bind('actual_amount')} />
        </FormField>
      </form>
    </Modal>
  );
}
