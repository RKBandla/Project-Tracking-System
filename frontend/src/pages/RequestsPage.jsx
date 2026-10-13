import { useState } from 'react';
import { requestsApi } from '../api/services';
import { useAuth } from '../auth/useAuth';
import { can } from '../auth/permissions';
import Badge from '../components/Badge';
import { DataTable, Pagination } from '../components/DataTable';
import { Alert, EmptyState, ErrorState, Loading } from '../components/Feedback';
import FormField from '../components/FormField';
import RequestForm from '../components/forms/RequestForm';
import { ConfirmDialog, Modal } from '../components/Modal';
import { FilterBar, PageHeader } from '../components/PageParts';
import { useAsync } from '../hooks/useAsync';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { Link } from '../router/Router';
import { useRouter } from '../router/routing';
import { REQUEST_STATUSES } from '../utils/constants';
import { formatDate, formatMoney, label } from '../utils/format';

const PAGE_SIZE = 20;

/**
 * Approve or reject a request with a note.
 *
 * @param {{request: object, decision: 'approve'|'reject', onDone: Function, onClose: Function}} props
 */
function ReviewDialog({ request, decision, onDone, onClose }) {
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const approve = decision === 'approve';

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      if (approve) await requestsApi.approve(request.id, note);
      else await requestsApi.reject(request.id, note);
      onDone();
    } catch (err) {
      setError(err.details?.review_note ? 'Please explain why the request is rejected.' : err.message);
      setBusy(false);
    }
  };

  return (
    <Modal
      title={approve ? 'Approve request' : 'Reject request'}
      onClose={onClose}
      size="sm"
      footer={(
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button type="submit" form="review-form" className={`btn ${approve ? 'btn-primary' : 'btn-danger'}`} disabled={busy}>
            {busy ? 'Saving…' : approve ? 'Approve and create project' : 'Reject'}
          </button>
        </>
      )}
    >
      <form id="review-form" className="form-stack" onSubmit={submit}>
        <p>
          <strong>{request.name}</strong> requested by {request.requested_by_name}
          {Number(request.proposed_budget) > 0 && <> · {formatMoney(request.proposed_budget)}</>}
        </p>
        {approve && <p className="muted">A project will be created with {request.requested_by_name} as manager.</p>}
        {error && <Alert kind="error">{error}</Alert>}
        <FormField label={approve ? 'Note (optional)' : 'Reason'} required={!approve}>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} />
        </FormField>
      </form>
    </Modal>
  );
}

/** Project requests: managers submit, admins review. */
export default function RequestsPage() {
  const { user } = useAuth();
  const { query: urlQuery, navigate } = useRouter();
  const isAdmin = can(user, 'requests:review');
  const [status, setStatus] = useState(isAdmin ? 'pending' : '');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [form, setForm] = useState(urlQuery.new ? 'new' : null);
  const [review, setReview] = useState(null);
  const [withdrawing, setWithdrawing] = useState(null);
  const [withdrawState, setWithdrawState] = useState({ busy: false, error: '' });
  const [notice, setNotice] = useState('');
  const q = useDebouncedValue(search);

  const query = { status, q, page, page_size: PAGE_SIZE };
  const { data, error, loading, reload } = useAsync(() => requestsApi.list(query), JSON.stringify(query));

  const closeForm = () => {
    setForm(null);
    if (urlQuery.new) navigate('/requests', { replace: true });
  };

  const saveRequest = async (body) => {
    if (form === 'new') await requestsApi.create(body);
    else await requestsApi.update(form.id, body);
    setNotice(form === 'new' ? 'Request submitted. An admin will review it.' : 'Request updated.');
    closeForm();
    reload();
  };

  const withdraw = async () => {
    setWithdrawState({ busy: true, error: '' });
    try {
      await requestsApi.withdraw(withdrawing.id);
      setWithdrawing(null);
      setWithdrawState({ busy: false, error: '' });
      reload();
    } catch (err) {
      setWithdrawState({ busy: false, error: err.message });
    }
  };

  const columns = [
    {
      key: 'name',
      label: 'Request',
      render: (r) => (
        <div className="cell-title">
          <strong>{r.name}</strong>
          {r.description && <span className="muted clamp">{r.description}</span>}
        </div>
      ),
    },
    ...(isAdmin ? [{ key: 'requested_by_name', label: 'Requested by' }] : []),
    { key: 'proposed_budget', label: 'Budget', className: 'num', render: (r) => formatMoney(r.proposed_budget) },
    {
      key: 'dates',
      label: 'Timeline',
      render: (r) => (r.proposed_start_date || r.proposed_end_date
        ? `${formatDate(r.proposed_start_date)} – ${formatDate(r.proposed_end_date)}` : '—'),
    },
    { key: 'created_at', label: 'Submitted', render: (r) => formatDate(r.created_at) },
    {
      key: 'status',
      label: 'Status',
      render: (r) => (
        <div className="cell-title">
          <Badge value={r.status} />
          {r.review_note && <span className="muted clamp" title={r.review_note}>“{r.review_note}”</span>}
        </div>
      ),
    },
    {
      key: 'actions',
      label: 'Actions',
      className: 'actions-cell',
      render: (r) => (
        <div className="row-actions">
          {r.project_id && <Link className="btn btn-ghost btn-sm" to={`/projects/${r.project_id}`}>View {r.project_code}</Link>}
          {isAdmin && r.status === 'pending' && (
            <>
              <button type="button" className="btn btn-primary btn-sm" onClick={() => setReview({ request: r, decision: 'approve' })}>Approve</button>
              <button type="button" className="btn btn-ghost btn-sm text-danger" onClick={() => setReview({ request: r, decision: 'reject' })}>Reject</button>
            </>
          )}
          {can(user, 'requests:edit', r) && (
            <>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setForm(r)}>Edit</button>
              <button type="button" className="btn btn-ghost btn-sm text-danger" onClick={() => setWithdrawing(r)}>Withdraw</button>
            </>
          )}
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title={isAdmin ? 'Project requests' : 'My project requests'}
        subtitle={isAdmin ? 'Review requests from managers. Approving creates the project.'
          : 'Ask an admin to create a project for you to manage.'}
        actions={can(user, 'requests:create') && (
          <button type="button" className="btn btn-primary" onClick={() => setForm('new')}>Request a project</button>
        )}
      />
      {notice && <Alert kind="success">{notice}</Alert>}

      <FilterBar>
        <input type="search" className="search-input" placeholder="Search requests…" aria-label="Search requests"
          value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
        <select aria-label="Filter by status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="">All statuses</option>
          {REQUEST_STATUSES.map((s) => <option key={s} value={s}>{label(s)}</option>)}
        </select>
      </FilterBar>

      {error && <ErrorState error={error} onRetry={reload} />}
      {loading && !data && <Loading />}
      {data && (
        <>
          <DataTable
            caption="Project requests"
            columns={columns}
            rows={data.items}
            empty={<EmptyState title={status === 'pending' ? 'No pending requests' : 'No requests found'} />}
          />
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />
        </>
      )}

      {form && <RequestForm request={form === 'new' ? null : form} onClose={closeForm} onSave={saveRequest} />}
      {review && (
        <ReviewDialog
          request={review.request}
          decision={review.decision}
          onClose={() => setReview(null)}
          onDone={() => {
            setNotice(review.decision === 'approve' ? `Approved “${review.request.name}”. The project has been created.` : `Rejected “${review.request.name}”.`);
            setReview(null);
            reload();
          }}
        />
      )}
      {withdrawing && (
        <ConfirmDialog
          title="Withdraw request?"
          message={<>Withdraw your request for <strong>{withdrawing.name}</strong>?</>}
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
