import { useState } from 'react';
import { budgetsApi } from '../../api/services';
import { DataTable } from '../../components/DataTable';
import { EmptyState, ErrorState, Loading } from '../../components/Feedback';
import BudgetItemForm from '../../components/forms/BudgetItemForm';
import { ConfirmDialog } from '../../components/Modal';
import { Card, FilterBar, StatCard } from '../../components/PageParts';
import { useAsync } from '../../hooks/useAsync';
import { BUDGET_CATEGORIES } from '../../utils/constants';
import { formatDate, formatMoney, label } from '../../utils/format';

/**
 * Budget line items (planned vs actual) for one project.
 *
 * @param {{project: object, canManage: boolean, onChanged: Function}} props
 */
export default function BudgetTab({ project, canManage, onChanged }) {
  const [category, setCategory] = useState('');
  const [sort, setSort] = useState('-entry_date');
  const [editing, setEditing] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [deleteState, setDeleteState] = useState({ busy: false, error: '' });

  const query = { project_id: project.id, category, sort, page_size: 100 };
  const { data, error, loading, reload } = useAsync(() => budgetsApi.list(query), JSON.stringify(query));

  const changed = () => { reload(); onChanged(); };

  const save = async (body) => {
    if (editing === 'new') await budgetsApi.create(body);
    else await budgetsApi.update(editing.id, body);
    setEditing(null);
    changed();
  };

  const remove = async () => {
    setDeleteState({ busy: true, error: '' });
    try {
      await budgetsApi.remove(deleting.id);
      setDeleting(null);
      setDeleteState({ busy: false, error: '' });
      changed();
    } catch (err) {
      setDeleteState({ busy: false, error: err.message });
    }
  };

  const columns = [
    { key: 'entry_date', label: 'Date', sortKey: 'entry_date', render: (b) => formatDate(b.entry_date) },
    { key: 'category', label: 'Category', sortKey: 'category', render: (b) => label(b.category) },
    { key: 'description', label: 'Description', sortKey: 'description' },
    { key: 'planned_amount', label: 'Planned', sortKey: 'planned_amount', className: 'num', render: (b) => formatMoney(b.planned_amount) },
    { key: 'actual_amount', label: 'Actual', sortKey: 'actual_amount', className: 'num', render: (b) => formatMoney(b.actual_amount) },
  ];
  if (canManage) {
    columns.push({
      key: 'actions',
      label: 'Actions',
      className: 'actions-cell',
      render: (b) => (
        <div className="row-actions">
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(b)}>Edit</button>
          <button type="button" className="btn btn-ghost btn-sm text-danger" onClick={() => setDeleting(b)}>Delete</button>
        </div>
      ),
    });
  }

  const totals = data?.totals || { planned: 0, actual: 0 };
  const remaining = Number(project.budget_total) - Number(totals.actual);

  return (
    <div className="tab-panel">
      <div className="stats-grid">
        <StatCard label="Total budget" value={formatMoney(project.budget_total)} />
        <StatCard label={category ? `Planned · ${label(category)}` : 'Planned'} value={formatMoney(totals.planned)} />
        <StatCard label={category ? `Spent · ${label(category)}` : 'Spent'} value={formatMoney(totals.actual)} />
        {!category && (
          <StatCard label="Remaining" value={formatMoney(remaining)} tone={remaining < 0 ? 'danger' : 'default'}
            hint={remaining < 0 ? 'Over budget' : undefined} />
        )}
      </div>
      <Card
        title="Budget items"
        actions={canManage && (
          <button type="button" className="btn btn-primary btn-sm" onClick={() => setEditing('new')}>Add item</button>
        )}
      >
        <FilterBar>
          <select aria-label="Filter by category" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All categories</option>
            {BUDGET_CATEGORIES.map((c) => <option key={c} value={c}>{label(c)}</option>)}
          </select>
        </FilterBar>
        {error && <ErrorState error={error} onRetry={reload} />}
        {loading && !data && <Loading />}
        {data && (
          <DataTable caption="Budget items" columns={columns} rows={data.items} sort={sort} onSort={setSort}
            empty={<EmptyState title="No budget items yet" />} />
        )}
      </Card>

      {editing && (
        <BudgetItemForm project={project} item={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)} onSave={save} />
      )}
      {deleting && (
        <ConfirmDialog
          title="Delete budget item?"
          message={<>Delete <strong>{deleting.description}</strong> ({formatMoney(deleting.actual_amount)} spent)?</>}
          confirmLabel="Delete"
          danger
          busy={deleteState.busy}
          error={deleteState.error}
          onConfirm={remove}
          onCancel={() => { setDeleting(null); setDeleteState({ busy: false, error: '' }); }}
        />
      )}
    </div>
  );
}
