import { useState } from 'react';
import { activityApi } from '../api/services';
import { useAsync } from '../hooks/useAsync';
import { useAuth } from '../auth/useAuth';
import { Link } from '../router/Router';
import { useRouter } from '../router/routing';
import { initials, label } from '../utils/format';
import Badge from './Badge';

const ICONS = {
  dashboard: 'M3 13h8V3H3zm0 8h8v-6H3zm10 0h8V11h-8zm0-18v6h8V3z',
  projects: 'M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8z',
  grid: 'M3 3h7v7H3zm11 0h7v7h-7zM3 14h7v7H3zm11 0h7v7h-7z',
  timesheet: 'M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2m1 11h-5v-2h3V6h2z',
  approve: 'M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z',
  requests: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zm-1 7V3.5L18.5 9zM8 13h8v2H8zm0 4h5v2H8z',
  people: 'M16 11a3 3 0 1 0-3-3 3 3 0 0 0 3 3m-8 0a3 3 0 1 0-3-3 3 3 0 0 0 3 3m0 2c-2.3 0-7 1.2-7 3.5V19h14v-2.5C15 14.2 10.3 13 8 13m8 0c-.3 0-.6 0-1 .1a4.2 4.2 0 0 1 2 3.4V19h6v-2.5c0-2.3-4.7-3.5-7-3.5',
  bell: 'M12 22a2 2 0 0 0 2-2h-4a2 2 0 0 0 2 2m6-6v-5a6 6 0 0 0-5-5.9V4a1 1 0 0 0-2 0v1.1A6 6 0 0 0 6 11v5l-2 2v1h16v-1z',
  audit: 'M13 3a9 9 0 0 0-9 9H1l4 4 4-4H6a7 7 0 1 1 2.1 5l-1.4 1.4A9 9 0 1 0 13 3m-1 5v5l4.3 2.5.7-1.2-3.5-2.1V8z',
  profile: 'M12 12a4 4 0 1 0-4-4 4 4 0 0 0 4 4m0 2c-2.7 0-8 1.3-8 4v2h16v-2c0-2.7-5.3-4-8-4',
};

/** Navigation entries for a role. */
function navItems(role) {
  const staff = role === 'admin' || role === 'manager';
  return [
    { to: '/', label: 'Dashboard', icon: 'dashboard' },
    { to: '/projects', label: role === 'employee' ? 'My projects' : 'Projects', icon: 'projects' },
    staff && { to: '/allocation', label: 'Allocation', icon: 'grid' },
    role === 'employee' && { to: '/timesheet', label: 'My timesheet', icon: 'timesheet' },
    staff && { to: '/approvals', label: 'Hours to approve', icon: 'approve' },
    staff && { to: '/requests', label: role === 'admin' ? 'Project requests' : 'My requests', icon: 'requests' },
    staff && { to: '/users', label: 'People', icon: 'people' },
    { to: '/notifications', label: 'Notifications', icon: 'bell', badge: true },
    role === 'admin' && { to: '/audit', label: 'Audit log', icon: 'audit' },
    { to: '/profile', label: 'My profile', icon: 'profile' },
  ].filter(Boolean);
}

function Icon({ name }) {
  return (
    <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d={ICONS[name]} fill="currentColor" />
    </svg>
  );
}

/**
 * Application shell: sidebar navigation on desktop, top bar with a menu on phones.
 *
 * @param {{children: React.ReactNode}} props
 */
export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const { path } = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  // Re-check unread notifications whenever the page changes
  const { data: unreadData } = useAsync(
    () => activityApi.notifications({ unread: 'true', page_size: 1 }).catch(() => null),
    `unread-${path}`,
  );
  const unread = unreadData?.unread || 0;
  const isActive = (to) => (to === '/' ? path === '/' : path === to || path.startsWith(`${to}/`));

  return (
    <div className={`app-shell ${menuOpen ? 'menu-open' : ''}`}>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="topbar">
        <button
          type="button"
          className="icon-btn menu-toggle"
          aria-label={menuOpen ? 'Close menu' : 'Open menu'}
          aria-expanded={menuOpen}
          aria-controls="sidebar"
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span className="hamburger" aria-hidden="true" />
        </button>
        <Link to="/" className="brand brand-small" onClick={() => setMenuOpen(false)}>
          <span className="brand-mark" aria-hidden="true" />
          <span>Project Tracker</span>
        </Link>
      </header>

      <aside id="sidebar" className="sidebar">
        <Link to="/" className="brand" onClick={() => setMenuOpen(false)}>
          <span className="brand-mark" aria-hidden="true" />
          <span>Project Tracking<br />System</span>
        </Link>
        <nav aria-label="Main">
          <ul className="nav-list">
            {navItems(user.role).map((item) => (
              <li key={item.to}>
                <Link
                  to={item.to}
                  className={`nav-link ${isActive(item.to) ? 'active' : ''}`}
                  aria-current={isActive(item.to) ? 'page' : undefined}
                  onClick={() => setMenuOpen(false)}
                >
                  <Icon name={item.icon} />
                  {item.label}
                  {item.badge && unread > 0 && (
                    <span className="nav-badge" aria-label={`${unread} unread`}>{unread > 99 ? '99+' : unread}</span>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div className="sidebar-user">
          <div className="avatar" aria-hidden="true">{initials(user.full_name)}</div>
          <div className="sidebar-user-text">
            <strong>{user.full_name}</strong>
            <span>{user.employee_id} · <Badge value={user.role} text={label(user.role)} /></span>
          </div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={logout}>Sign out</button>
        </div>
      </aside>
      <div className="scrim" onClick={() => setMenuOpen(false)} aria-hidden="true" />

      <main id="main" className="main" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
