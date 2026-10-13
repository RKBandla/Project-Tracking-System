import { useState } from 'react';
import { Modal } from './Modal';

/**
 * Shows a newly generated employee ID and password exactly once.
 *
 * @param {{title: string, name: string, employeeId: string, password: string, onClose: Function}} props
 */
export default function CredentialsDialog({ title, name, employeeId, password, onClose }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(`Employee ID: ${employeeId}\nPassword: ${password}`);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <Modal
      title={title}
      onClose={onClose}
      size="sm"
      footer={(
        <>
          <button type="button" className="btn btn-ghost" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
          <button type="button" className="btn btn-primary" onClick={onClose}>Done</button>
        </>
      )}
    >
      <p>Share these sign-in details with <strong>{name}</strong>.</p>
      <dl className="credentials">
        <div><dt>Employee ID</dt><dd><code>{employeeId}</code></dd></div>
        <div><dt>Password</dt><dd><code>{password}</code></dd></div>
      </dl>
      <p className="alert alert-warning">This password is shown only once and is not stored in readable form. If it is lost, reset it.</p>
    </Modal>
  );
}
