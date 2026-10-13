import { createContext, useContext } from 'react';

/** Context holding `{ user, ready, login, logout, setUser }` (provided by AuthProvider). */
export const AuthContext = createContext(null);

/** @returns {{user: object|null, ready: boolean, login: Function, logout: Function, setUser: Function}} */
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
