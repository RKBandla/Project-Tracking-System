/**
 * Loading, error and empty states.
 */

/**
 * Inline alert message.
 *
 * @param {{kind?: 'error'|'success'|'info'|'warning', children: React.ReactNode}} props
 */
export function Alert({ kind = 'info', children }) {
  return (
    <div className={`alert alert-${kind}`} role={kind === 'error' ? 'alert' : 'status'}>
      {children}
    </div>
  );
}

/**
 * Spinner with an accessible label.
 *
 * @param {{label?: string}} props
 */
export function Loading({ label = 'Loading…' }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

/**
 * Error state with a retry button.
 *
 * @param {{error: Error, onRetry?: Function}} props
 */
export function ErrorState({ error, onRetry }) {
  return (
    <Alert kind="error">
      <span>{error?.message || 'Something went wrong.'}</span>
      {onRetry && (
        <button type="button" className="btn btn-ghost btn-sm" onClick={onRetry}>Try again</button>
      )}
    </Alert>
  );
}

/**
 * Friendly empty state.
 *
 * @param {{title: string, children?: React.ReactNode}} props
 */
export function EmptyState({ title, children }) {
  return (
    <div className="empty-state">
      <p className="empty-title">{title}</p>
      {children && <div className="muted">{children}</div>}
    </div>
  );
}
