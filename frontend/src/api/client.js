/**
 * HTTP client for the backend services.
 *
 * Every service lives at `${VITE_API_URL}/api/<service>` (CloudFront on AWS,
 * the CORS proxy locally). Tokens are kept in localStorage; an expired access
 * token is refreshed once automatically before the request is retried.
 */

const API_URL = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '');
const STORAGE_KEY = 'pts.session';

/** Error thrown for non-2xx responses, carrying the API error body. */
export class ApiError extends Error {
  /**
   * @param {number} status HTTP status code
   * @param {string} message Human readable message
   * @param {object} [details] Field errors or rule details from the API
   */
  constructor(status, message, details) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

/** @returns {{access_token: string, refresh_token: string}|null} */
export function loadSession() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || null;
  } catch {
    return null;
  }
}

/** @param {{access_token: string, refresh_token: string}|null} session */
export function saveSession(session) {
  try {
    if (session) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        access_token: session.access_token,
        refresh_token: session.refresh_token,
      }));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // storage unavailable (private mode); the session lives only in memory
  }
}

let onUnauthorized = () => {};

/** Register a callback invoked when the session can no longer be refreshed. */
export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler;
}

/** Build a URL with query parameters, skipping empty values. */
export function buildUrl(service, path = '', query = {}) {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') params.append(key, value);
  });
  const qs = params.toString();
  return `${API_URL}/api/${service}${path}${qs ? `?${qs}` : ''}`;
}

async function parse(res) {
  if (res.status === 204) return null;
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return { error: { message: text } };
  }
}

let refreshing = null;

async function refreshTokens() {
  const session = loadSession();
  if (!session?.refresh_token) return false;
  // share one refresh between concurrent requests
  refreshing = refreshing || fetch(buildUrl('auth', '/refresh'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: session.refresh_token }),
  })
    .then(async (res) => {
      if (!res.ok) return false;
      saveSession(await res.json());
      return true;
    })
    .catch(() => false)
    .finally(() => { refreshing = null; });
  return refreshing;
}

/**
 * Call an API endpoint.
 *
 * @param {string} service Service name, e.g. 'projects'
 * @param {string} [path] Path below the service, e.g. '/5/archive'
 * @param {{method?: string, body?: object, query?: object, auth?: boolean}} [options]
 * @returns {Promise<any>} Parsed JSON body (null for 204)
 */
export async function request(service, path = '', { method = 'GET', body, query, auth = true } = {}) {
  const send = () => {
    const headers = { 'Content-Type': 'application/json' };
    const session = loadSession();
    if (auth && session?.access_token) headers.Authorization = `Bearer ${session.access_token}`;
    return fetch(buildUrl(service, path, query), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  };

  let res;
  try {
    res = await send();
    if (res.status === 401 && auth && await refreshTokens()) {
      res = await send();
    }
  } catch {
    throw new ApiError(0, 'Cannot reach the server. Check your connection and try again.');
  }

  const data = await parse(res);
  if (!res.ok) {
    if (res.status === 401 && auth) onUnauthorized();
    const err = data?.error || {};
    throw new ApiError(res.status, err.message || `Request failed (${res.status})`, err.details);
  }
  return data;
}
