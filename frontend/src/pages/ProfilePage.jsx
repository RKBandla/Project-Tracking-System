import { useState } from 'react';
import { usersApi } from '../api/services';
import { useAuth } from '../auth/useAuth';
import Badge from '../components/Badge';
import { Alert, EmptyState } from '../components/Feedback';
import FormField from '../components/FormField';
import HoursBar from '../components/HoursBar';
import { Card, DetailList, PageHeader } from '../components/PageParts';
import { useAsync } from '../hooks/useAsync';
import { useForm } from '../hooks/useForm';
import { Link } from '../router/Router';
import { formatDate, formatMoney, initials } from '../utils/format';

/** The signed-in user's details. Only first name, last name and email are editable. */
export default function ProfilePage() {
  const { user, setUser } = useAuth();
  const [saved, setSaved] = useState(false);
  const { data: workload } = useAsync(
    () => (user.role === 'admin' ? Promise.resolve(null) : usersApi.workload(user.id)),
    `workload-${user.id}`,
  );
  const { bind, errors, formError, busy, handleSubmit } = useForm({
    first_name: user.first_name,
    last_name: user.last_name,
    email: user.email,
  });

  const submit = handleSubmit(async (values) => {
    setSaved(false);
    const updated = await usersApi.updateMe(values);
    setUser({ ...user, ...updated });
    setSaved(true);
  });

  return (
    <>
      <PageHeader title="My profile" subtitle="Your account and current workload." />
      <div className="two-col">
        <Card>
          <div className="profile-head">
            <div className="avatar avatar-lg" aria-hidden="true">{initials(user.full_name)}</div>
            <div>
              <h2>{user.full_name}</h2>
              <p className="muted">{user.job_title}</p>
              <Badge value={user.role} />
            </div>
          </div>
          <DetailList
            items={[
              ['Employee ID', <code key="id">{user.employee_id}</code>],
              ['Email', user.email],
              ['Manager', user.manager_name || '—'],
              ['Salary', user.salary == null ? '—' : formatMoney(user.salary)],
              ['Member since', formatDate(user.created_at)],
            ]}
          />
        </Card>

        <Card title="Edit personal information">
          <form className="form-stack" onSubmit={submit} noValidate>
            <p className="muted">You can change your name and email. Ask an administrator to update anything else.</p>
            {saved && <Alert kind="success">Your details have been saved.</Alert>}
            {formError && <Alert kind="error">{formError}</Alert>}
            <FormField label="First name" required error={errors.first_name}>
              <input {...bind('first_name')} maxLength={100} autoComplete="given-name" />
            </FormField>
            <FormField label="Last name" required error={errors.last_name}>
              <input {...bind('last_name')} maxLength={100} autoComplete="family-name" />
            </FormField>
            <FormField label="Email" required error={errors.email}>
              <input type="email" {...bind('email')} autoComplete="email" />
            </FormField>
            <div>
              <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? 'Saving…' : 'Save changes'}</button>
            </div>
          </form>
        </Card>
      </div>

      {workload && (
        <Card title="My weekly workload" actions={<HoursBar hours={workload.allocated_hours} />}>
          {workload.assignments.length ? (
            <ul className="item-list">
              {workload.assignments.map((a) => (
                <li key={a.id}>
                  <Link to={`/projects/${a.project_id}`} className="item-link">
                    <span><strong>{a.project_name}</strong><span className="muted"> {a.project_code} {a.project_role && `· ${a.project_role}`}</span></span>
                    <span className="pill">{a.hours_per_week} h/wk</span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : <EmptyState title="No current assignments" />}
        </Card>
      )}
    </>
  );
}
