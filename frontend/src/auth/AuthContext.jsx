/**
 * Authentication state: the signed-in user, login and logout.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { loadSession, saveSession, setUnauthorizedHandler } from '../api/client';
import { authApi } from '../api/services';
import { AuthContext } from './useAuth';

/**
 * Provides `{ user, ready, login, logout, setUser }` to the app.
 *
 * @param {{children: React.ReactNode}} props
 */
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(() => !loadSession());

  const logout = useCallback(() => {
    saveSession(null);
    setUser(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(logout);
  }, [logout]);

  useEffect(() => {
    if (ready) return;
    authApi.me()
      .then(setUser)
      .catch(() => saveSession(null))
      .finally(() => setReady(true));
  }, [ready]);

  const login = useCallback(async (username, password) => {
    const session = await authApi.login(username, password);
    saveSession(session);
    setUser(session.user);
    return session.user;
  }, []);

  const value = useMemo(() => ({ user, ready, login, logout, setUser }), [user, ready, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
