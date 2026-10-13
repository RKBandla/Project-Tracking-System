import { useState } from 'react';
import { projectsApi } from '../api/services';
import { useAuth } from '../auth/useAuth';
import { can } from '../auth/permissions';
import Badge from '../components/Badge';
import BudgetBar from '../components/BudgetBar';
import { DataTable, Pagination } from '../components/DataTable';
import { EmptyState, ErrorState, Loading } from '../components/Feedback';
import ProjectForm from '../components/forms/ProjectForm';
import { FilterBar, PageHeader } from '../components/PageParts';
import { useAsync } from '../hooks/useAsync';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { Link } from '../router/Router';
import { useRouter } from '../router/routing';
import { PROJECT_STATUSES } from '../utils/constants';
import { formatDate, label } from '../utils/format';

const PAGE_SIZE = 20;

function Progress({ done, total }) {
  const pct = total ? Math.round((done / total) * 100) : 0;
  return (
    <div className="progress-cell" title={`${done} of ${total} deliverables done`}>
      <div className="progress-track"><div className="progress-fill" style={{ width: `${pct}%` }} /></div>
      <span className="muted">{total ? `${pct}%` : '—'}</span>
    </div>
  );
}

/** Searchable, filterable list of the projects the user can see. */
export default function ProjectsPage() {
  const { user } = useAuth();
  const { navigate, query: urlQuery } = useRouter();
  const [search, setSearch] = useState('');
  const [filters, setFilters] = useState({ status: '', at_risk: urlQuery.at_risk || '', archived: 'false' });
  const [sort, setSort] = useState('name');
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const q = useDebouncedValue(search);

  const query = { q, ...filters, sort, page, page_size: PAGE_SIZE };
  const { data, error, loading, reload } = useAsync(() => projectsApi.list(query), JSON.stringify(query));

  const setFilter = (name, value) => {
    setFilters((prev) => ({ ...prev, [name]: value }));
    setPage(1);
  };

  const columns = [
    {
      key: 'name',
      label: 'Project',
      sortKey: 'name',
      render: (p) => (
        <div className="cell-title">
          <Link to={`/projects/${p.id}`} onClick={(e) => e.stopPropagation()}>{p.name}</Link>
          <span className="muted">{p.code} · {p.manager_name || 'No manager'}{p.is_archived ? ' · Archived' : ''}</span>
        </div>
      ),
    },
    { key: 'status', label: 'Status', sortKey: 'status', render: (p) => <Badge value={p.status} /> },
    {
      key: 'risk',
      label: 'Risk',
      render: (p) => (p.is_archived ? '—' : (
        <span title={p.risk_reasons.join('\n') || 'On track'}>
          <Badge value={p.at_risk ? 'at_risk' : 'on_track'} dot />
        </span>
      )),
    },
    { key: 'end_date', label: 'Ends', sortKey: 'end_date', render: (p) => formatDate(p.end_date) },
    { key: 'progress', label: 'Deliverables', render: (p) => <Progress done={p.deliverables_done} total={p.deliverable_count} /> },
    {
      key: 'budget',
      label: 'Budget used',
      sortKey: 'consumed_cents',
      render: (p) => <BudgetBar compact budget={p.budget_cents} planned={p.planned_cents} consumed={p.consumed_cents} />,
    },
  ];

  const isEmployee = user.role === 'employee';
  const filtered = q || filters.status || filters.at_risk;
  return (
    <>
      <PageHeader
        title={isEmployee ? 'My projects' : 'Projects'}
        subtitle={isEmployee ? 'Projects you are currently booked on.'
          : user.role === 'manager' ? 'Projects you manage.' : 'Every project in the organisation.'}
        actions={(
          <>
            {can(user, 'projects:create') && (
              <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>New project</button>
            )}
            {can(user, 'requests:create') && (
              <button type="button" className="btn btn-primary" onClick={() => navigate('/requests?new=1')}>Request a project</button>
            )}
          </>
        )}
      />

      <FilterBar>
        <input
          type="search"
          className="search-input"
          placeholder="Search name, code, manager…"
          aria-label="Search projects"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
        />
        <select aria-label="Filter by status" value={filters.status} onChange={(e) => setFilter('status', e.target.value)}>
          <option value="">All statuses</option>
          {PROJECT_STATUSES.map((s) => <option key={s} value={s}>{label(s)}</option>)}
        </select>
        <select aria-label="Filter by risk" value={filters.at_risk} onChange={(e) => setFilter('at_risk', e.target.value)}>
          <option value="">Any risk</option>
          <option value="true">At risk</option>
          <option value="false">On track</option>
        </select>
        {!isEmployee && (
          <select aria-label="Archived projects" value={filters.archived} onChange={(e) => setFilter('archived', e.target.value)}>
            <option value="false">Active projects</option>
            <option value="true">Archived only</option>
            <option value="all">Active and archived</option>
          </select>
        )}
      </FilterBar>

      {error && <ErrorState error={error} onRetry={reload} />}
      {loading && !data && <Loading />}
      {data && (
        <div className={loading ? 'is-refreshing' : undefined}>
          <DataTable
            caption="Projects"
            columns={columns}
            rows={data.items}
            sort={sort}
            onSort={(s) => { setSort(s); setPage(1); }}
            onRowClick={(p) => navigate(`/projects/${p.id}`)}
            rowLabel={(p) => `Open ${p.name}`}
            empty={(
              <EmptyState title={filtered ? 'No projects match your filters' : 'No projects yet'}>
                {isEmployee && !filtered && 'Your manager will book you onto projects.'}
              </EmptyState>
            )}
          />
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />
        </div>
      )}

      {creating && (
        <ProjectForm
          onClose={() => setCreating(false)}
          onSave={async (body) => {
            const project = await projectsApi.create(body);
            setCreating(false);
            navigate(`/projects/${project.id}`);
          }}
        />
      )}
    </>
  );
}
