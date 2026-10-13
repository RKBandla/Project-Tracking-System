import { describe, expect, it, vi } from 'vitest';
import { mockApi, signIn } from '../test/mockApi';
import { ApiError, buildUrl, loadSession, request, saveSession, setUnauthorizedHandler } from './client';

describe('buildUrl', () => {
  it('skips empty query values', () => {
    expect(buildUrl('projects', '/5', { q: 'a b', status: '', page: 2, x: null }))
      .toMatch(/\/api\/projects\/5\?q=a\+b&page=2$/);
  });
});

describe('request', () => {
  it('sends the bearer token and JSON body', async () => {
    signIn();
    const fetchMock = mockApi({ 'POST /api/projects': { id: 1 } });
    const result = await request('projects', '', { method: 'POST', body: { name: 'X' } });
    expect(result).toEqual({ id: 1 });
    const [, options] = fetchMock.mock.calls[0];
    expect(options.headers.Authorization).toBe('Bearer access');
    expect(JSON.parse(options.body)).toEqual({ name: 'X' });
  });

  it('returns null for 204 responses', async () => {
    mockApi({ 'DELETE /api/deliverables/1': { status: 204, body: null } });
    expect(await request('deliverables', '/1', { method: 'DELETE' })).toBeNull();
  });

  it('throws ApiError with message and field details', async () => {
    mockApi({
      'POST /api/users': { status: 400, body: { error: { code: 'bad_request', message: 'Validation failed', details: { email: 'bad' } } } },
    });
    const err = await request('users', '', { method: 'POST', body: {} }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(400);
    expect(err.details).toEqual({ email: 'bad' });
  });

  it('refreshes an expired token once and retries', async () => {
    signIn();
    let calls = 0;
    mockApi({
      'GET /api/projects': ({ headers }) => {
        calls += 1;
        return headers.Authorization === 'Bearer new-access'
          ? { items: [] }
          : { status: 401, body: { error: { message: 'Token has expired' } } };
      },
      'POST /api/auth/refresh': { access_token: 'new-access', refresh_token: 'new-refresh' },
    });
    expect(await request('projects')).toEqual({ items: [] });
    expect(calls).toBe(2);
    expect(loadSession().access_token).toBe('new-access');
  });

  it('signs out when the refresh fails', async () => {
    signIn();
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    mockApi({
      'GET /api/projects': { status: 401, body: { error: { message: 'expired' } } },
      'POST /api/auth/refresh': { status: 401, body: { error: { message: 'expired' } } },
    });
    await expect(request('projects')).rejects.toMatchObject({ status: 401 });
    expect(onUnauthorized).toHaveBeenCalled();
    setUnauthorizedHandler(() => {});
  });

  it('reports network failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    await expect(request('projects')).rejects.toMatchObject({ status: 0 });
  });

  it('saves and clears the session', () => {
    saveSession({ access_token: 'a', refresh_token: 'r', user: { id: 1 } });
    expect(loadSession()).toEqual({ access_token: 'a', refresh_token: 'r' });
    saveSession(null);
    expect(loadSession()).toBeNull();
  });
});
