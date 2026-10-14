import { useState } from 'react';
import { useAuth } from '../auth/useAuth';
import FormField from '../components/FormField';
import { Alert } from '../components/Feedback';

/** Sign-in with a username (first and last name) or email, and a password. */
export default function LoginPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const onSubmit = async (event) => {
    event.preventDefault();
    setError('');
    setBusy(true);
    try {
      await login(username.trim(), password);
    } catch (err) {
      setError(err.status === 400 ? 'Enter your username or email, and your password.' : err.message);
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
          <li>40-hour weekly capacity</li>
          <li>Planned vs consumed budget</li>
          <li>Timesheets and approvals</li>
        </ul>
      </section>
      <main className="login-panel">
        <form className="login-form" onSubmit={onSubmit} noValidate>
          <h1>Sign in</h1>
          <p className="muted">Use your full name or your work email, and the password provided by your administrator.</p>
          {error && <Alert kind="error">{error}</Alert>}
          <FormField label="Username or email" required hint="Your first and last name (e.g. Jane Doe) or your work email.">
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoCapitalize="words"
              spellCheck={false}
              placeholder="Jane Doe or jane.doe@company.com"
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
