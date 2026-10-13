import { useState } from 'react';
import { useAuth } from '../auth/useAuth';
import { Link } from '../router/Router';
import { useRouter } from '../router/routing';
import { initials, label } from '../utils/format';
import Badge from './Badge';

const ICONS = {
  dashboard: 'M3 13h8V3H3zm0 8h8v-6H3zm10 0h8V11h-8zm0-18v6h8V3z',
  projects: 'M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8z',
  requests: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zm-1 7V3.5L18.5 9zM8 13h8v2H8zm0 4h5v2H8z',
  people: 'M16 11a3 3 0 1 0-3-3 3 3 0 0 0 3 3m-8 0a3 3 0 1 0-3-3 3 3 0 0 0 3 3m0 2c-2.3 0-7 1.2-7 3.5V19h14v-2.5C15 14.2 10.3 13 8 13m8 0c-.3 0-.6 0-1 .1a4.2 4.2 0 0 1 2 3.4V19h6v-2.5c0-2.3-4.7-3.5-7-3.5',
  profile: 'M12 12a4 4 0 1 0-4-4 4 4 0 0 0 4 4m0 2c-2.7 0-8 1.3-8 4v2h16v-2c0-2.7-5.3-4-8-4',
};

/** Navigation entries for a role. */
function navItems(role) {
  const items = [{ to: '/', label: 'Dashboard', icon: 'dashboard' }];
  items.push({ to: '/projects', label: role === 'employee' ? 'My projects' : 'Projects', icon: 'projects' });
  if (role === 'admin') items.push({ to: '/requests', label: 'Project requests', icon: 'requests' });
  if (role === 'manager') items.push({ to: '/requests', label: 'My requests', icon: 'requests' });
  if (role === 'admin') items.push({ to: '/users', label: 'Users', icon: 'people' });
  if (role === 'manager') items.push({ to: '/users', label: 'My team', icon: 'people' });
  items.push({ to: '/profile', label: 'My profile', icon: 'profile' });
  return items;
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
