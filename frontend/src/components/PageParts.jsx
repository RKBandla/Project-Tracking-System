/**
 * Small layout building blocks used by every page.
 */

/**
 * Page title row with optional subtitle and action buttons.
 *
 * @param {{title: React.ReactNode, subtitle?: React.ReactNode, actions?: React.ReactNode,
 *          eyebrow?: React.ReactNode}} props
 */
export function PageHeader({ title, subtitle, actions, eyebrow }) {
  return (
    <div className="page-header">
      <div className="page-heading">
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

/**
 * Metric tile.
 *
 * @param {{label: string, value: React.ReactNode, hint?: React.ReactNode, tone?: string}} props
 */
export function StatCard({ label, value, hint, tone = 'default' }) {
  return (
    <div className={`stat stat-${tone}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

/**
 * Titled content card.
 *
 * @param {{title?: React.ReactNode, actions?: React.ReactNode, children: React.ReactNode,
 *          className?: string}} props
 */
export function Card({ title, actions, children, className = '' }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-header">
          {title && <h2>{title}</h2>}
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

/**
 * Accessible tab list. Content is rendered by the parent based on `active`.
 *
 * @param {{tabs: {id: string, label: string}[], active: string, onChange: Function}} props
 */
export function Tabs({ tabs, active, onChange }) {
  const onKeyDown = (event, index) => {
    const delta = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    if (!delta) return;
    const next = tabs[(index + delta + tabs.length) % tabs.length];
    onChange(next.id);
    document.getElementById(`tab-${next.id}`)?.focus();
  };
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab, index) => (
        <button
          key={tab.id}
          id={`tab-${tab.id}`}
          type="button"
          role="tab"
          aria-selected={active === tab.id}
          tabIndex={active === tab.id ? 0 : -1}
          className={`tab ${active === tab.id ? 'active' : ''}`}
          onClick={() => onChange(tab.id)}
          onKeyDown={(e) => onKeyDown(e, index)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

/**
 * Horizontal row of filter controls that wraps on small screens.
 *
 * @param {{children: React.ReactNode}} props
 */
export function FilterBar({ children }) {
  return <div className="filter-bar" role="search">{children}</div>;
}

/**
 * Definition list for read-only details.
 *
 * @param {{items: [string, React.ReactNode][]}} props
 */
export function DetailList({ items }) {
  return (
    <dl className="details">
      {items.map(([term, value]) => (
        <div key={term} className="details-row">
          <dt>{term}</dt>
          <dd>{value ?? '—'}</dd>
        </div>
      ))}
    </dl>
  );
}
