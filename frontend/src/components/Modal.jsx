import { useEffect, useId, useRef } from 'react';

/**
 * Accessible modal dialog. Closes on Escape or backdrop click.
 *
 * @param {{title: string, onClose: Function, children: React.ReactNode, footer?: React.ReactNode,
 *          size?: 'sm'|'md'|'lg'}} props
 */
export function Modal({ title, onClose, children, footer, size = 'md' }) {
  const titleId = useId();
  const panelRef = useRef(null);
  const closeRef = useRef(onClose);

  useEffect(() => {
    closeRef.current = onClose;
  });

  // Runs once per opening so typing in the form never steals focus back
  useEffect(() => {
    const previous = document.activeElement;
    const focusable = panelRef.current?.querySelector('input, select, textarea, button:not(.modal-close)');
    (focusable || panelRef.current)?.focus();
    const onKey = (event) => { if (event.key === 'Escape') closeRef.current(); };
    document.addEventListener('keydown', onKey);
    document.body.classList.add('modal-open');
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.classList.remove('modal-open');
      previous?.focus?.();
    };
  }, []);

  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div
        className={`modal modal-${size}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={panelRef}
        tabIndex={-1}
      >
        <header className="modal-header">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="icon-btn modal-close" onClick={onClose} aria-label="Close">×</button>
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-footer">{footer}</footer>}
      </div>
    </div>
  );
}

/**
 * Confirmation dialog for destructive or important actions.
 *
 * @param {{title: string, message: React.ReactNode, confirmLabel?: string, danger?: boolean,
 *          busy?: boolean, error?: string, onConfirm: Function, onCancel: Function}} props
 */
export function ConfirmDialog({
  title, message, confirmLabel = 'Confirm', danger = false, busy = false, error, onConfirm, onCancel,
}) {
  return (
    <Modal
      title={title}
      onClose={onCancel}
      size="sm"
      footer={(
        <>
          <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>Cancel</button>
          <button
            type="button"
            className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? 'Working…' : confirmLabel}
          </button>
        </>
      )}
    >
      <div className="confirm-message">{message}</div>
      {error && <p className="alert alert-error" role="alert">{error}</p>}
    </Modal>
  );
}
