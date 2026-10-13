import { usersApi } from '../../api/services';
import { MAX_WEEKLY_HOURS } from '../../auth/permissions';
import { useAsync } from '../../hooks/useAsync';
import { toNumber, useForm } from '../../hooks/useForm';
import { addDays, formatShortDate, mondayOf, today } from '../../utils/format';
import { Alert } from '../Feedback';
import FormField from '../FormField';
import { Modal } from '../Modal';

/** Weeks (Monday dates) between two YYYY-MM-DD dates, capped at 26. */
function weeksBetween(start, end) {
  if (!start || !end || end < start) return [];
  const weeks = [];
  for (let w = mondayOf(start); w <= end && weeks.length < 26; w = addDays(w, 7)) weeks.push(w);
  return weeks;
}

/**
 * Book a person onto a project for N hours per week between two dates, or change
 * a booking. Shows the person's existing weekly load so clashes with the 40-hour
 * limit are visible before saving; the server refuses them either way.
 *
 * @param {{project: object, assignment?: object, onSave: Function, onClose: Function}} props
 */
export default function AssignmentForm({ project, assignment, onSave, onClose }) {
  const editing = Boolean(assignment);
  const { data: people, loading: peopleLoading } = useAsync(
    () => (editing ? Promise.resolve(null) : usersApi.list({ is_active: 'true', page_size: 100, sort: 'name' })),
    `bookable-${editing}`,
  );
  const candidates = (people?.items || []).filter((p) => p.role !== 'admin');
  const defaultStart = project.start_date && project.start_date > today() ? project.start_date : today();

  const { values, bind, errors, formError, busy, handleSubmit } = useForm({
    user_id: assignment?.user_id ?? '',
    hours_per_week: assignment?.hours_per_week ?? 8,
    start_date: assignment?.start_date || defaultStart,
    end_date: assignment?.end_date || project.end_date || addDays(defaultStart, 27),
    project_role: assignment?.project_role || '',
  });

  const userId = toNumber(values.user_id);
  const weeks = weeksBetween(values.start_date, values.end_date);
  const { data: workload } = useAsync(
    () => (userId && weeks.length
      ? usersApi.workload(userId, { from: weeks[0], weeks: weeks.length }).catch(() => null)
      : Promise.resolve(null)),
    `workload-${userId}-${weeks[0]}-${weeks.length}`,
  );
  const requested = toNumber(values.hours_per_week) || 0;
  const loadByWeek = Object.fromEntries((workload?.weeks || []).map((w) => [w.week_start, w.hours]));
  const preview = weeks.map((week) => {
    const existing = (loadByWeek[week] || 0) - (editing ? assignment.hours_per_week : 0);
    return { week, existing: Math.max(existing, 0), total: Math.max(existing, 0) + requested };
  });
  const clashes = preview.filter((w) => w.total > MAX_WEEKLY_HOURS);

  const submit = handleSubmit(async (v) => {
    const body = {
      hours_per_week: toNumber(v.hours_per_week),
      start_date: v.start_date,
      end_date: v.end_date,
      project_role: v.project_role,
    };
    if (!editing) {
      body.project_id = project.id;
      body.user_id = toNumber(v.user_id);
    }
    await onSave(body);
  });

  return (
    <Modal
      title={editing ? `Edit booking: ${assignment.full_name}` : `Book someone on ${project.name}`}
      onClose={onClose}
      size="lg"
      footer={(
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button type="submit" form="assignment-form" className="btn btn-primary" disabled={busy}>
            {busy ? 'Saving…' : editing ? 'Save' : 'Book'}
          </button>
        </>
      )}
    >
      <form id="assignment-form" className="form-grid" onSubmit={submit} noValidate>
        {formError && <div className="span-all"><Alert kind="error">{formError}</Alert></div>}
        {!editing && (
          <FormField label="Person" required error={errors.user_id} className="span-all">
            <select {...bind('user_id')}>
              <option value="">{peopleLoading ? 'Loading…' : 'Select a person'}</option>
              {candidates.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.full_name} · {p.job_title} ({p.current_week_hours}/{MAX_WEEKLY_HOURS} h this week)
                </option>
              ))}
            </select>
          </FormField>
        )}
        <FormField label="Hours per week" required error={errors.hours_per_week} hint="1–40">
          <input type="number" min="1" max={MAX_WEEKLY_HOURS} step="1" inputMode="numeric" {...bind('hours_per_week')} />
        </FormField>
        <FormField label="Role on project" error={errors.project_role}>
          <input {...bind('project_role')} maxLength={100} placeholder="e.g. Developer, QA" />
        </FormField>
        <FormField label="From" required error={errors.start_date}>
          <input type="date" {...bind('start_date')} />
        </FormField>
        <FormField label="Until" required error={errors.end_date}>
          <input type="date" {...bind('end_date')} />
        </FormField>
        {userId && preview.length > 0 && (
          <div className="span-all workload-preview">
            <span className="muted">Weekly load with this booking ({MAX_WEEKLY_HOURS} h limit)</span>
            <div className="week-strip">
              {preview.map((w) => (
                <span key={w.week} className={`week-chip ${w.total > MAX_WEEKLY_HOURS ? 'over' : w.total === MAX_WEEKLY_HOURS ? 'full' : ''}`}
                  title={`${w.existing} h already booked`}>
                  <small>{formatShortDate(w.week)}</small>{w.total} h
                </span>
              ))}
            </div>
            {clashes.length > 0 && (
              <span className="text-danger">
                {clashes.length} week{clashes.length > 1 ? 's' : ''} over 40 hours — this booking will be refused.
              </span>
            )}
          </div>
        )}
      </form>
    </Modal>
  );
}
