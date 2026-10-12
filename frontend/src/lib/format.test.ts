import { describe, expect, it } from 'vitest';
import { formatShortDate, trimmedLength } from './format';

describe('format', () => {
  it('shows a bare date as that calendar day in every time zone', () => {
    const expected = new Date(2026, 9, 5).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    expect(formatShortDate('2026-10-05')).toBe(expected);
  });

  it('leaves text that is not a date alone', () => {
    expect(formatShortDate('not a date')).toBe('not a date');
  });

  it('counts characters without surrounding whitespace', () => {
    expect(trimmedLength('  abc \n')).toBe(3);
  });
});
