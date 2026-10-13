import { createContext, useContext } from 'react';

/** Context holding `{ path, query, navigate }` (provided by RouterProvider). */
export const RouterContext = createContext(null);

/** @returns {{path: string, query: object, navigate: Function}} */
export function useRouter() {
  const ctx = useContext(RouterContext);
  if (!ctx) throw new Error('useRouter must be used inside RouterProvider');
  return ctx;
}

/**
 * Match a pattern like `/projects/:id` against a path.
 *
 * @returns {object|null} Route params, or null when it does not match
 */
export function matchPath(pattern, path) {
  const patternParts = pattern.split('/').filter(Boolean);
  const pathParts = path.split('/').filter(Boolean);
  if (patternParts.length !== pathParts.length) return null;
  const params = {};
  for (let i = 0; i < patternParts.length; i += 1) {
    const part = patternParts[i];
    if (part.startsWith(':')) params[part.slice(1)] = decodeURIComponent(pathParts[i]);
    else if (part !== pathParts[i]) return null;
  }
  return params;
}
