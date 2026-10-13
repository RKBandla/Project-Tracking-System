import { useState } from 'react';
import { useAuth } from '../auth/useAuth';
import FormField from '../components/FormField';
import { Alert } from '../components/Feedback';

/** Sign-in with employee ID and password. */
export default function LoginPage() {
  const { login } = useAuth();
  const [employeeId, setEmployeeId] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const onSubmit = async (event) => {
    event.preventDefault();
    setError('');
    setBusy(true);
    try {
      await login(employeeId.trim(), password);
    } catch (err) {
      setError(err.status === 400 ? 'Enter your employee ID and password.' : err.message);
      setBusy(false);
    }
  };

  return (
    <div className="login-page">
      <section className="login-hero" aria-hidden="true">
        <div className="brand brand-light">
          <span className="brand-mark" />
          <span>Project Tracking System</span>
        </div>
        <div>
          <h2>Every project, person and dollar in one place.</h2>
          <p>Track delivery health, team capacity and budgets without leaving the browser.</p>
        </div>
        <ul className="login-points">
          <li>Real-time project health</li>
          <li>40-hour capacity planning</li>
          <li>Budget burn at a glance</li>
        </ul>
      </section>
      <main className="login-panel">
        <form className="login-form" onSubmit={onSubmit} noValidate>
          <h1>Sign in</h1>
          <p className="muted">Use the employee ID and password provided by your administrator.</p>
          {error && <Alert kind="error">{error}</Alert>}
          <FormField label="Employee ID" required>
            <input
              value={employeeId}
              onChange={(e) => setEmployeeId(e.target.value)}
              autoComplete="username"
              autoCapitalize="characters"
              placeholder="e.g. EMP0001"
            />
          </FormField>
          <FormField label="Password" required>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </FormField>
          <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </main>
    </div>
  );
}
