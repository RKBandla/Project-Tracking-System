import { describe, expect, it } from 'vitest';
import { matchPath } from '../router/routing';
import {
  addDays, centsToDollars, dollarsToCents, fieldErrors, formatCents, formatDate, formatHours, formatMoney,
  initials, label, mondayOf, timeAgo, today,
} from './format';

describe('format helpers', () => {
  it('labels enum values', () => {
    expect(label('on_hold')).toBe('On hold');
    expect(label('at_risk')).toBe('At risk');
    expect(label('time_entry')).toBe('Time entry');
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

  it('handles money as whole cents', () => {
    expect(formatCents(123456)).toBe('$1,234.56');
    expect(formatCents(100000)).toBe('$1,000');
    expect(dollarsToCents('12.345')).toBe(1235);
    expect(dollarsToCents('')).toBeNull();
    expect(centsToDollars(1250)).toBe('12.5');
    expect(centsToDollars(null)).toBe('');
  });

  it('does date arithmetic on YYYY-MM-DD strings', () => {
    expect(addDays('2026-01-30', 3)).toBe('2026-02-02');
    expect(mondayOf('2026-10-18')).toBe('2026-10-12'); // Sunday -> Monday
    expect(mondayOf('2026-10-12')).toBe('2026-10-12');
    expect(formatHours(7.5)).toBe('7.5 h');
  });

  it('formats relative times', () => {
    const now = new Date('2026-10-13T12:00:00Z').getTime();
    expect(timeAgo('2026-10-13T11:59:30Z', now)).toBe('just now');
    expect(timeAgo('2026-10-13T11:30:00Z', now)).toBe('30 min ago');
    expect(timeAgo('2026-10-13T09:00:00Z', now)).toBe('3 h ago');
    expect(timeAgo('2026-10-10T09:00:00Z', now)).toBe('Oct 10, 2026');
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
