import { useState } from 'react';
import { timesheetsApi } from '../api/services';
import { useAuth } from '../auth/useAuth';
import { can } from '../auth/permissions';
import Badge from '../components/Badge';
import { DataTable, Pagination } from '../components/DataTable';
import { Alert, EmptyState, ErrorState, Loading } from '../components/Feedback';
import FormField from '../components/FormField';
import { Modal } from '../components/Modal';
import { FilterBar, PageHeader } from '../components/PageParts';
import { useAsync } from '../hooks/useAsync';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { TIME_ENTRY_STATUSES } from '../utils/constants';
import { formatDate, formatHours, label } from '../utils/format';

const PAGE_SIZE = 25;

/**
 * Ask for a reason before rejecting hours.
 *
 * @param {{entry: object, onDone: Function, onClose: Function}} props
 */
function RejectDialog({ entry, onDone, onClose }) {
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    try {
      await timesheetsApi.reject(entry.id, note);
      onDone();
    } catch (err) {
      setError(err.details?.review_note ? 'Please give a reason.' : err.message);
      setBusy(false);
    }
  };
  return (
    <Modal title="Reject hours" onClose={onClose} size="sm" footer={(
      <>
        <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
        <button type="submit" form="reject-form" className="btn btn-danger" disabled={busy}>{busy ? 'Saving…' : 'Reject'}</button>
      </>
    )}>
      <form id="reject-form" className="form-stack" onSubmit={submit}>
        <p>{entry.full_name}: {formatHours(entry.hours)} on {entry.project_name}, {formatDate(entry.work_date)}</p>
        {error && <Alert kind="error">{error}</Alert>}
        <FormField label="Reason" required>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} />
        </FormField>
      </form>
    </Modal>
  );
}

/** Hours to approve: managers see their direct reports' entries, admins everyone's. */
export default function ApprovalsPage() {
  const { user } = useAuth();
  const [status, setStatus] = useState('pending');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState([]);
  const [rejecting, setRejecting] = useState(null);
  const [notice, setNotice] = useState('');
  const [actionError, setActionError] = useState('');
  const q = useDebouncedValue(search);

  const query = status === 'pending'
    ? { reviewable: 'true', q, page, page_size: PAGE_SIZE }
    : { status, q, page, page_size: PAGE_SIZE };
  const { data, error, loading, reload } = useAsync(() => timesheetsApi.list(query), JSON.stringify(query));
  const reviewable = (data?.items || []).filter((e) => can(user, 'timesheets:review', e));

  const done = (message) => { setNotice(message); setSelected([]); setActionError(''); reload(); };
  const approve = async (ids) => {
    try {
      await (ids.length === 1 ? timesheetsApi.approve(ids[0]) : timesheetsApi.approveBatch(ids));
      done(`Approved ${ids.length} ${ids.length === 1 ? 'entry' : 'entries'}.`);
    } catch (err) {
      setActionError(err.message);
    }
  };
  const toggle = (id) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  const columns = [
    ...(status === 'pending' ? [{
      key: 'select',
      label: 'Select',
      render: (e) => (can(user, 'timesheets:review', e) ? (
        <input type="checkbox" aria-label={`Select ${e.full_name} ${e.work_date}`} checked={selected.includes(e.id)} onChange={() => toggle(e.id)} />
      ) : null),
    }] : []),
    { key: 'full_name', label: 'Person', render: (e) => <div className="cell-title"><strong>{e.full_name}</strong><span className="muted">{e.employee_id}</span></div> },
    { key: 'work_date', label: 'Date', render: (e) => formatDate(e.work_date) },
    { key: 'project_name', label: 'Project', render: (e) => <div className="cell-title"><strong>{e.project_name}</strong>{e.note && <span className="muted clamp">{e.note}</span>}</div> },
    { key: 'hours', label: 'Hours', className: 'num', render: (e) => formatHours(e.hours) },
    { key: 'status', label: 'Status', render: (e) => <Badge value={e.status} /> },
    {
      key: 'actions',
      label: 'Actions',
      className: 'actions-cell',
      render: (e) => (can(user, 'timesheets:review', e) ? (
        <div className="row-actions">
          <button type="button" className="btn btn-primary btn-sm" onClick={() => approve([e.id])}>Approve</button>
          <button type="button" className="btn btn-ghost btn-sm text-danger" onClick={() => setRejecting(e)}>Reject</button>
        </div>
      ) : null),
    },
  ];

  return (
    <>
      <PageHeader
        title="Hours to approve"
        subtitle={user.role === 'admin' ? 'Approve anyone\'s logged hours. Only approved hours count as consumed budget.'
          : 'Approve hours logged by your direct reports. Only approved hours count as consumed budget.'}
        actions={status === 'pending' && reviewable.length > 0 && (
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setSelected(reviewable.map((e) => e.id))}>Select all</button>
            <button type="button" className="btn btn-primary" disabled={!selected.length} onClick={() => approve(selected)}>
              Approve selected ({selected.length})
            </button>
          </>
        )}
      />
      {notice && <Alert kind="success">{notice}</Alert>}
      {actionError && <Alert kind="error">{actionError}</Alert>}
      <FilterBar>
        <input type="search" className="search-input" placeholder="Search person, project, note…" aria-label="Search entries"
          value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
        <select aria-label="Filter by status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); setSelected([]); }}>
          {TIME_ENTRY_STATUSES.map((s) => <option key={s} value={s}>{s === 'pending' ? 'Waiting for me' : label(s)}</option>)}
        </select>
      </FilterBar>
      {error && <ErrorState error={error} onRetry={reload} />}
      {loading && !data && <Loading />}
      {data && (
        <>
          <DataTable caption="Time entries" columns={columns} rows={data.items}
            empty={<EmptyState title={status === 'pending' ? 'Nothing waiting for approval' : 'No entries'} />} />
          <p className="muted">Total: {formatHours(data.total_hours)}</p>
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />
        </>
      )}
      {rejecting && (
        <RejectDialog entry={rejecting} onClose={() => setRejecting(null)}
          onDone={() => { setRejecting(null); done('Entry rejected.'); }} />
      )}
    </>
  );
}
