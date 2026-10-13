import { describe, expect, it } from 'vitest';
import { matchPath } from '../router/routing';
import { fieldErrors, formatDate, formatMoney, initials, label, today } from './format';

describe('format helpers', () => {
  it('labels enum values', () => {
    expect(label('on_hold')).toBe('On hold');
    expect(label('amber')).toBe('At risk');
    expect(label('some_new_value')).toBe('some new value');
    expect(label(null)).toBe('');
  });

  it('formats dates without timezone drift', () => {
    expect(formatDate('2026-03-04')).toBe('Mar 4, 2026');
    expect(formatDate('2026-03-04T23:59:00+00:00')).toBe('Mar 4, 2026');
    expect(formatDate(null)).toBe('—');
    expect(formatDate('garbage')).toBe('—');
  });

  it('formats money', () => {
    expect(formatMoney(1500)).toBe('$1,500');
    expect(formatMoney(1500.5)).toBe('$1,500.50');
    expect(formatMoney(null)).toBe('$0');
  });

  it('builds initials', () => {
    expect(initials('Ada Lovelace King')).toBe('AL');
    expect(initials('')).toBe('?');
  });

  it('returns today as YYYY-MM-DD', () => {
    expect(today()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it('extracts field errors', () => {
    expect(fieldErrors({ details: { name: 'is required' } })).toEqual({ name: 'is required' });
    expect(fieldErrors({ details: [1] })).toEqual({});
    expect(fieldErrors(null)).toEqual({});
  });
});

describe('matchPath', () => {
  it('matches static and parameterised paths', () => {
    expect(matchPath('/', '/')).toEqual({});
    expect(matchPath('/projects/:id', '/projects/42')).toEqual({ id: '42' });
    expect(matchPath('/projects/:id', '/projects')).toBeNull();
    expect(matchPath('/projects', '/users')).toBeNull();
    expect(matchPath('/projects/', '/projects')).toEqual({});
  });
});
