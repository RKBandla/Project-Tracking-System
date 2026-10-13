import { useState } from 'react';
import { usersApi } from '../api/services';
import { useAuth } from '../auth/useAuth';
import { can, ROLES } from '../auth/permissions';
import Badge from '../components/Badge';
import CredentialsDialog from '../components/CredentialsDialog';
import { DataTable, Pagination } from '../components/DataTable';
import { EmptyState, ErrorState, Loading } from '../components/Feedback';
import UserForm from '../components/forms/UserForm';
import HoursBar from '../components/HoursBar';
import { ConfirmDialog } from '../components/Modal';
import { FilterBar, PageHeader } from '../components/PageParts';
import { useAsync } from '../hooks/useAsync';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { formatMoney, label } from '../utils/format';

const PAGE_SIZE = 20;

/** Admin: all users with create/edit/reset. Manager: read-only view of direct reports. */
export default function UsersPage() {
  const { user, setUser } = useAuth();
  const isAdmin = can(user, 'users:edit');
  const [search, setSearch] = useState('');
  const [role, setRole] = useState('');
  const [active, setActive] = useState('true');
  const [sort, setSort] = useState('name');
  const [page, setPage] = useState(1);
  const [form, setForm] = useState(null); // null | 'new' | user
  const [credentials, setCredentials] = useState(null);
  const [resetting, setResetting] = useState(null);
  const [resetState, setResetState] = useState({ busy: false, error: '' });
  const q = useDebouncedValue(search);

  const query = { q, role, is_active: active, sort, page, page_size: PAGE_SIZE };
  const { data, error, loading, reload } = useAsync(() => usersApi.list(query), JSON.stringify(query));

  const save = async (body) => {
    if (form === 'new') {
      const created = await usersApi.create(body);
      setCredentials({ title: 'User created', name: created.user.full_name, employeeId: created.employee_id, password: created.temporary_password });
    } else {
      const updated = await usersApi.update(form.id, body);
      if (updated.id === user.id) setUser({ ...user, ...updated });
    }
    setForm(null);
    reload();
  };

  const resetPassword = async () => {
    setResetState({ busy: true, error: '' });
    try {
      const res = await usersApi.resetPassword(resetting.id);
      setCredentials({ title: 'Password reset', name: resetting.full_name, employeeId: res.employee_id, password: res.temporary_password });
      setResetting(null);
      setResetState({ busy: false, error: '' });
    } catch (err) {
      setResetState({ busy: false, error: err.message });
    }
  };

  const columns = [
    {
      key: 'name',
      label: 'Name',
      sortKey: 'name',
      render: (u) => (
        <div className="cell-title"><strong>{u.full_name}</strong><span className="muted">{u.employee_id} · {u.email}</span></div>
      ),
    },
    { key: 'job_title', label: 'Job title', sortKey: 'job_title' },
    { key: 'role', label: 'Role', sortKey: 'role', render: (u) => <Badge value={u.role} /> },
    ...(isAdmin ? [{ key: 'manager_name', label: 'Manager', render: (u) => u.manager_name || '—' }] : []),
    {
      key: 'allocated_hours',
      label: 'Weekly load',
      sortKey: 'allocated_hours',
      render: (u) => (u.role === 'admin' ? '—' : <HoursBar hours={u.allocated_hours} compact />),
    },
    { key: 'salary', label: 'Salary', className: 'num', render: (u) => (u.salary == null ? '—' : formatMoney(u.salary)) },
    ...(isAdmin ? [{
      key: 'status',
      label: 'Status',
      render: (u) => <Badge value={u.is_active ? 'completed' : 'inactive'} text={u.is_active ? 'Active' : 'Inactive'} />,
    }, {
      key: 'actions',
      label: 'Actions',
      className: 'actions-cell',
      render: (u) => (
        <div className="row-actions">
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setForm(u)}>Edit</button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setResetting(u)}>Reset password</button>
        </div>
      ),
    }] : []),
  ];

  return (
    <>
      <PageHeader
        title={isAdmin ? 'Users' : 'My team'}
        subtitle={isAdmin ? 'Create accounts, assign roles and managers.' : 'People who report to you and their weekly load.'}
        actions={can(user, 'users:create') && (
          <button type="button" className="btn btn-primary" onClick={() => setForm('new')}>New user</button>
        )}
      />

      <FilterBar>
        <input type="search" className="search-input" placeholder="Search name, ID, email, title…" aria-label="Search people"
          value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
        {isAdmin && (
          <>
            <select aria-label="Filter by role" value={role} onChange={(e) => { setRole(e.target.value); setPage(1); }}>
              <option value="">All roles</option>
              {ROLES.map((r) => <option key={r} value={r}>{label(r)}</option>)}
            </select>
            <select aria-label="Filter by status" value={active} onChange={(e) => { setActive(e.target.value); setPage(1); }}>
              <option value="true">Active</option>
              <option value="false">Inactive</option>
              <option value="">All</option>
            </select>
          </>
        )}
      </FilterBar>

      {error && <ErrorState error={error} onRetry={reload} />}
      {loading && !data && <Loading />}
      {data && (
        <>
          <DataTable
            caption="People"
            columns={columns}
            rows={data.items}
            sort={sort}
            onSort={(s) => { setSort(s); setPage(1); }}
            empty={<EmptyState title={isAdmin ? 'No users match' : 'No one reports to you yet'} />}
          />
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />
        </>
      )}

      {form && (
        <UserForm user={form === 'new' ? null : form} currentUserId={user.id} onClose={() => setForm(null)} onSave={save} />
      )}
      {resetting && (
        <ConfirmDialog
          title="Reset password?"
          message={<>Generate a new password for <strong>{resetting.full_name}</strong>? Their current password stops working immediately.</>}
          confirmLabel="Reset password"
          busy={resetState.busy}
          error={resetState.error}
          onConfirm={resetPassword}
          onCancel={() => { setResetting(null); setResetState({ busy: false, error: '' }); }}
        />
      )}
      {credentials && <CredentialsDialog {...credentials} onClose={() => setCredentials(null)} />}
    </>
  );
}
