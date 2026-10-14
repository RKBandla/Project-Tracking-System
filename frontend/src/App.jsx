import { useEffect } from 'react';
import { AuthProvider } from './auth/AuthContext';
import { useAuth } from './auth/useAuth';
import { EmptyState, Loading } from './components/Feedback';
import Layout from './components/Layout';
import AllocationPage from './pages/AllocationPage';
import ApprovalsPage from './pages/ApprovalsPage';
import AuditPage from './pages/AuditPage';
import DashboardPage from './pages/DashboardPage';
import LoginPage from './pages/LoginPage';
import NotificationsPage from './pages/NotificationsPage';
import ProfilePage from './pages/ProfilePage';
import ProjectDetailPage from './pages/ProjectDetailPage';
import ProjectsPage from './pages/ProjectsPage';
import RequestsPage from './pages/RequestsPage';
import TimesheetPage from './pages/TimesheetPage';
import UsersPage from './pages/UsersPage';
import { Link, RouterProvider } from './router/Router';
import { matchPath, useRouter } from './router/routing';

/** Route table: path pattern, page and the roles allowed to open it. */
const STAFF = ['admin', 'manager'];
const ROUTES = [
  { path: '/', title: 'Dashboard', render: () => <DashboardPage /> },
  { path: '/projects', title: 'Projects', render: () => <ProjectsPage /> },
  { path: '/projects/:id', title: 'Project', render: ({ id }) => <ProjectDetailPage key={id} id={id} /> },
  { path: '/allocation', title: 'Allocation', roles: STAFF, render: () => <AllocationPage /> },
  { path: '/timesheet', title: 'My timesheet', roles: ['employee'], render: () => <TimesheetPage /> },
  { path: '/approvals', title: 'Hours to approve', roles: STAFF, render: () => <ApprovalsPage /> },
  { path: '/requests', title: 'Project requests', roles: STAFF, render: () => <RequestsPage /> },
  { path: '/users', title: 'People', roles: STAFF, render: () => <UsersPage /> },
  { path: '/notifications', title: 'Notifications', render: () => <NotificationsPage /> },
  { path: '/audit', title: 'Audit log', roles: ['admin'], render: () => <AuditPage /> },
  { path: '/profile', title: 'My profile', render: () => <ProfilePage /> },
];

function NotFound() {
  return (
    <EmptyState title="Page not found">
      <Link to="/">Go to the dashboard</Link>
    </EmptyState>
  );
}

function Routes() {
  const { user, ready } = useAuth();
  const { path, navigate } = useRouter();

  let match = null;
  for (const route of ROUTES) {
    const params = matchPath(route.path, path);
    if (params) {
      match = { route, params };
      break;
    }
  }

  useEffect(() => {
    document.title = `${match?.route.title || 'Not found'} · Project Tracking System`;
  }, [match?.route.title]);

  useEffect(() => {
    if (ready && user && path === '/login') navigate('/', { replace: true });
  }, [ready, user, path, navigate]);

  if (!ready) return <div className="center-screen"><Loading label="Starting…" /></div>;
  if (!user) return <LoginPage />;

  let page;
  if (!match) page = <NotFound />;
  else if (match.route.roles && !match.route.roles.includes(user.role)) {
    page = <EmptyState title="You do not have access to this page"><Link to="/">Go to the dashboard</Link></EmptyState>;
  } else page = match.route.render(match.params);

  return <Layout>{page}</Layout>;
}

/** Application root. */
export default function App() {
  return (
    <RouterProvider>
      <AuthProvider>
        <Routes />
      </AuthProvider>
    </RouterProvider>
  );
}
