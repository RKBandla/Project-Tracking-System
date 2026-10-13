import { useState } from 'react';
import { timesheetsApi } from '../api/services';
import Badge from '../components/Badge';
import { DataTable } from '../components/DataTable';
import { Alert, EmptyState, ErrorState, Loading } from '../components/Feedback';
import FormField from '../components/FormField';
import { ConfirmDialog } from '../components/Modal';
import { Card, PageHeader, StatCard } from '../components/PageParts';
import { useAsync } from '../hooks/useAsync';
import { toNumber, useForm } from '../hooks/useForm';
import { addDays, formatDate, formatDay, formatHours, mondayOf, today } from '../utils/format';

/**
 * Log or edit hours for one day on a booked project.
 *
 * @param {{week: object, entry?: object, onSaved: Function, onCancel: Function}} props
 */
function EntryForm({ week, entry, onSaved, onCancel }) {
  const days = week.days.map((d) => d.date).filter((d) => d <= today());
  const { bind, errors, formError, busy, handleSubmit } = useForm({
    project_id: entry?.project_id ?? week.bookings[0]?.project_id ?? '',
    work_date: entry?.work_date || (days.includes(today()) ? today() : days.at(-1) || week.week_start),
    hours: entry?.hours ?? 8,
    note: entry?.note || '',
  });
  const submit = handleSubmit(async (v) => {
    const body = { project_id: toNumber(v.project_id), work_date: v.work_date, hours: Number(v.hours), note: v.note };
    if (entry) await timesheetsApi.update(entry.id, body);
    else await timesheetsApi.create(body);
    onSaved();
  });
  return (
    <form className="entry-form" onSubmit={submit} noValidate aria-label={entry ? 'Edit hours' : 'Log hours'}>
      {formError && <Alert kind="error">{formError}</Alert>}
      <div className="entry-fields">
        <FormField label="Project" required error={errors.project_id}>
          <select {...bind('project_id')}>
            {week.bookings.map((b) => <option key={b.project_id} value={b.project_id}>{b.project_name} ({b.hours_per_week} h/wk)</option>)}
          </select>
        </FormField>
        <FormField label="Day" required error={errors.work_date}>
          <select {...bind('work_date')}>
            {week.days.map((d) => <option key={d.date} value={d.date} disabled={d.date > today()}>{formatDay(d.date)}</option>)}
          </select>
        </FormField>
        <FormField label="Hours" required error={errors.hours} hint="Quarter hours">
          <input type="number" min="0.25" max="24" step="0.25" inputMode="decimal" {...bind('hours')} />
        </FormField>
        <FormField label="Note" error={errors.note}>
          <input {...bind('note')} maxLength={1000} placeholder="What did you work on?" />
        </FormField>
      </div>
      <div className="entry-actions">
        {onCancel && <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancel</button>}
        <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? 'Saving…' : entry ? 'Save' : 'Log hours'}</button>
      </div>
    </form>
  );
}

/** Employee's weekly timesheet: bookings, daily totals, entries and their approval state. */
export default function TimesheetPage() {
  const [start, setStart] = useState(mondayOf(today()));
  const [editing, setEditing] = useState(null);
  const [withdrawing, setWithdrawing] = useState(null);
  const [withdrawState, setWithdrawState] = useState({ busy: false, error: '' });
  const { data: week, error, loading, reload } = useAsync(() => timesheetsApi.week(start), `week-${start}`);

  const withdraw = async () => {
    setWithdrawState({ busy: true, error: '' });
    try {
      await timesheetsApi.withdraw(withdrawing.id);
      setWithdrawing(null);
      setWithdrawState({ busy: false, error: '' });
      reload();
    } catch (err) {
      setWithdrawState({ busy: false, error: err.message });
    }
  };

  const columns = [
    { key: 'work_date', label: 'Day', render: (e) => formatDay(e.work_date) },
    { key: 'project_name', label: 'Project', render: (e) => <div className="cell-title"><strong>{e.project_name}</strong>{e.note && <span className="muted clamp">{e.note}</span>}</div> },
    { key: 'hours', label: 'Hours', className: 'num', render: (e) => formatHours(e.hours) },
    {
      key: 'status',
      label: 'Status',
      render: (e) => (
        <div className="cell-title">
          <Badge value={e.status} />
          {e.review_note && <span className="muted clamp">“{e.review_note}”</span>}
        </div>
      ),
    },
    {
      key: 'actions',
      label: 'Actions',
      className: 'actions-cell',
      render: (e) => (e.status === 'pending' ? (
        <div className="row-actions">
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(e)}>Edit</button>
          <button type="button" className="btn btn-ghost btn-sm text-danger" onClick={() => setWithdrawing(e)}>Withdraw</button>
        </div>
      ) : null),
    },
  ];

  return (
    <>
      <PageHeader
        title="My timesheet"
        subtitle="Log the hours you work on projects you are booked on. Your manager approves them."
        actions={(
          <div className="segmented" role="group" aria-label="Change week">
            <button type="button" onClick={() => setStart(addDays(start, -7))} aria-label="Previous week">‹</button>
            <button type="button" onClick={() => setStart(mondayOf(today()))}>This week</button>
            <button type="button" onClick={() => setStart(addDays(start, 7))} aria-label="Next week" disabled={start >= mondayOf(today())}>›</button>
          </div>
        )}
      />
      {error && <ErrorState error={error} onRetry={reload} />}
      {loading && !week && <Loading />}
      {week && (
        <>
          <p className="eyebrow">Week of {formatDate(week.week_start)}</p>
          <div className="stats-grid">
            <StatCard label="Booked" value={formatHours(week.booked_hours)} hint="Planned by your managers" />
            <StatCard label="Logged" value={formatHours(week.logged_hours)} hint="Pending + approved" />
            <StatCard label="Approved" value={formatHours(week.approved_hours)} tone="info" />
            <StatCard label="Projects" value={week.bookings.length} />
          </div>
          <div className="day-strip" aria-label="Hours per day">
            {week.days.map((d) => (
              <div key={d.date} className={`day-cell ${d.date === today() ? 'today' : ''}`}>
                <span>{formatDay(d.date)}</span>
                <strong>{Number(d.hours) ? formatHours(d.hours) : '—'}</strong>
              </div>
            ))}
          </div>
          <Card title="Log hours">
            {week.bookings.length ? (
              <EntryForm key={`${start}-new`} week={week} onSaved={reload} />
            ) : (
              <EmptyState title="You are not booked on any project this week" />
            )}
          </Card>
          <Card title="Entries this week">
            <DataTable caption="Time entries" columns={columns} rows={week.entries}
              empty={<EmptyState title="No hours logged this week" />} />
          </Card>
          {editing && (
            <Card title="Edit entry">
              <EntryForm key={editing.id} week={week} entry={editing}
                onSaved={() => { setEditing(null); reload(); }} onCancel={() => setEditing(null)} />
            </Card>
          )}
        </>
      )}
      {withdrawing && (
        <ConfirmDialog
          title="Withdraw these hours?"
          message={<>Withdraw {formatHours(withdrawing.hours)} on {withdrawing.project_name}? The entry is kept but won&apos;t be reviewed.</>}
          confirmLabel="Withdraw"
          danger
          busy={withdrawState.busy}
          error={withdrawState.error}
          onConfirm={withdraw}
          onCancel={() => { setWithdrawing(null); setWithdrawState({ busy: false, error: '' }); }}
        />
      )}
    </>
  );
}
