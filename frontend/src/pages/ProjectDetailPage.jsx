import { useState } from 'react';
import { projectsApi } from '../api/services';
import { useAuth } from '../auth/useAuth';
import { can } from '../auth/permissions';
import Badge from '../components/Badge';
import { Alert, EmptyState, ErrorState, Loading } from '../components/Feedback';
import ProjectForm from '../components/forms/ProjectForm';
import { ConfirmDialog } from '../components/Modal';
import { PageHeader, Tabs } from '../components/PageParts';
import { useAsync } from '../hooks/useAsync';
import { Link } from '../router/Router';
import { useRouter } from '../router/routing';
import BudgetTab from './project/BudgetTab';
import DeliverablesTab from './project/DeliverablesTab';
import DependencyTab from './project/DependencyTab';
import OverviewTab from './project/OverviewTab';
import ResourcesTab from './project/ResourcesTab';

/**
 * One project with tabs for overview, deliverables, dependencies, resources and budget.
 *
 * @param {{id: string}} props Project id from the URL
 */
export default function ProjectDetailPage({ id }) {
  const { user } = useAuth();
  const { query, navigate } = useRouter();
  const { data: summary, error, loading, reload } = useAsync(() => projectsApi.summary(id), `summary-${id}`);
  const [editing, setEditing] = useState(false);
  const [confirm, setConfirm] = useState(null); // 'archive' | 'reactivate'
  const [confirmState, setConfirmState] = useState({ busy: false, error: '' });

  if (loading && !summary) return <Loading />;
  if (error && !summary) {
    if (error.status === 404) {
      return (
        <EmptyState title="Project not found">
          It may not exist, or you may not have access. <Link to="/projects">Back to projects</Link>
        </EmptyState>
      );
    }
    return <ErrorState error={error} onRetry={reload} />;
  }

  const { project } = summary;
  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'deliverables', label: `Deliverables (${summary.deliverables.total})` },
    { id: 'dependencies', label: 'Dependencies' },
    { id: 'resources', label: 'Resources' },
    { id: 'budget', label: 'Budget' },
  ];
  const active = tabs.some((t) => t.id === query.tab) ? query.tab : 'overview';
  const setTab = (tab) => navigate(`/projects/${id}${tab === 'overview' ? '' : `?tab=${tab}`}`, { replace: true });

  const runConfirm = async () => {
    setConfirmState({ busy: true, error: '' });
    try {
      if (confirm === 'archive') await projectsApi.archive(project.id);
      else await projectsApi.reactivate(project.id);
      setConfirm(null);
      setConfirmState({ busy: false, error: '' });
      reload();
    } catch (err) {
      setConfirmState({ busy: false, error: err.message });
    }
  };

  return (
    <>
      <PageHeader
        eyebrow={<><Link to="/projects">Projects</Link> / {project.code}</>}
        title={project.name}
        subtitle={(
          <span className="badge-row">
            <Badge value={project.status} />
            {!project.is_archived && <Badge value={project.at_risk ? 'at_risk' : 'on_track'} dot />}
            {project.is_archived && <Badge value="archived" text="Archived" />}
            <span>Managed by {project.manager_name || 'nobody yet'}</span>
          </span>
        )}
        actions={(
          <>
            {can(user, 'projects:edit', project) && (
              <button type="button" className="btn btn-secondary" onClick={() => setEditing(true)}>Edit</button>
            )}
            {can(user, 'projects:archive') && (
              project.is_archived
                ? <button type="button" className="btn btn-primary" onClick={() => setConfirm('reactivate')}>Reactivate</button>
                : <button type="button" className="btn btn-ghost text-danger" onClick={() => setConfirm('archive')}>Archive</button>
            )}
          </>
        )}
      />

      {project.is_archived && (
        <Alert kind="warning">This project is archived and read-only. {can(user, 'projects:archive') && 'Reactivate it to make changes.'}</Alert>
      )}

      <Tabs tabs={tabs} active={active} onChange={setTab} />

      <div role="tabpanel" aria-labelledby={`tab-${active}`}>
        {active === 'overview' && <OverviewTab summary={summary} />}
        {active === 'deliverables' && (
          <DeliverablesTab project={project} members={summary.team.members}
            canManage={can(user, 'deliverables:manage', project)} onChanged={reload} />
        )}
        {active === 'dependencies' && <DependencyTab project={project} />}
        {active === 'resources' && (
          <ResourcesTab project={project} canManage={can(user, 'resources:manage', project)}
            showCost={user.role !== 'employee'} onChanged={reload} />
        )}
        {active === 'budget' && (
          <BudgetTab project={project} canManage={can(user, 'budgets:manage', project)} onChanged={reload} />
        )}
      </div>

      {editing && (
        <ProjectForm
          project={project}
          onClose={() => setEditing(false)}
          onSave={async (body) => {
            await projectsApi.update(project.id, body);
            setEditing(false);
            reload();
          }}
        />
      )}
      {confirm && (
        <ConfirmDialog
          title={confirm === 'archive' ? 'Archive project?' : 'Reactivate project?'}
          message={confirm === 'archive'
            ? <>Archive <strong>{project.name}</strong>? It becomes read-only and its bookings stop counting towards anyone&apos;s 40 hours. Nothing is deleted, so cost history is kept.</>
            : <>Reactivate <strong>{project.name}</strong>? Its bookings will count towards the 40-hour weekly limit again.</>}
          confirmLabel={confirm === 'archive' ? 'Archive' : 'Reactivate'}
          danger={confirm === 'archive'}
          busy={confirmState.busy}
          error={confirmState.error}
          onConfirm={runConfirm}
          onCancel={() => { setConfirm(null); setConfirmState({ busy: false, error: '' }); }}
        />
      )}
    </>
  );
}
