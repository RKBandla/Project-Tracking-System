import { useState } from 'react';
import { activityApi } from '../api/services';
import Badge from '../components/Badge';
import { DataTable, Pagination } from '../components/DataTable';
import { EmptyState, ErrorState, Loading } from '../components/Feedback';
import { FilterBar, PageHeader } from '../components/PageParts';
import { useAsync } from '../hooks/useAsync';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { AUDIT_ENTITIES } from '../utils/constants';
import { label } from '../utils/format';

const PAGE_SIZE = 50;

/** Admin audit log: one row for every create, edit and archive, newest first. */
export default function AuditPage() {
  const [search, setSearch] = useState('');
  const [entity, setEntity] = useState('');
  const [action, setAction] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [page, setPage] = useState(1);
  const q = useDebouncedValue(search);
  const query = { q, entity, action, from, to, page, page_size: PAGE_SIZE };
  const { data, error, loading, reload } = useAsync(() => activityApi.audit(query), JSON.stringify(query));
  const reset = (setter) => (e) => { setter(e.target.value); setPage(1); };

  const columns = [
    { key: 'created_at', label: 'When', render: (a) => new Date(a.created_at).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' }) },
    { key: 'actor_name', label: 'Who', render: (a) => <div className="cell-title"><strong>{a.actor_name}</strong>{a.actor_role && <span className="muted">{label(a.actor_role)}</span>}</div> },
    { key: 'action', label: 'Action', render: (a) => <Badge value={a.action} /> },
    { key: 'entity', label: 'Record', render: (a) => `${label(a.entity)} #${a.entity_id}` },
    { key: 'summary', label: 'What happened', render: (a) => a.summary },
  ];

  return (
    <>
      <PageHeader title="Audit log" subtitle="Every create, edit and archive in the system. Nothing is ever deleted." />
      <FilterBar>
        <input type="search" className="search-input" placeholder="Search summary or person…" aria-label="Search audit log"
          value={search} onChange={reset(setSearch)} />
        <select aria-label="Filter by record type" value={entity} onChange={reset(setEntity)}>
          <option value="">All records</option>
          {AUDIT_ENTITIES.map((e) => <option key={e} value={e}>{label(e)}</option>)}
        </select>
        <select aria-label="Filter by action" value={action} onChange={reset(setAction)}>
          <option value="">All actions</option>
          {['create', 'update', 'archive'].map((a) => <option key={a} value={a}>{label(a)}</option>)}
        </select>
        <input type="date" aria-label="From date" value={from} onChange={reset(setFrom)} />
        <input type="date" aria-label="To date" value={to} onChange={reset(setTo)} />
      </FilterBar>
      {error && <ErrorState error={error} onRetry={reload} />}
      {loading && !data && <Loading />}
      {data && (
        <>
          <DataTable caption="Audit log" columns={columns} rows={data.items} empty={<EmptyState title="No matching changes" />} />
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />
        </>
      )}
    </>
  );
}
