import { describe, expect, it } from 'vitest';
import { makeUserId, USER_ID_RE } from './userId';

const ODD_NAMES = [
  'Jordan',
  'José Ñúñez',
  'Zoë 🚀',
  '🚀🚀',
  '名前',
  '   ',
  '',
  "Mary-Jane O'Neil",
  '--leading and trailing--',
  'Ünïcödé   with   spaces',
  'a'.repeat(200),
  'x',
];

describe('makeUserId', () => {
  it.each(ODD_NAMES)('always matches the server rule for %j', (name) => {
    expect(makeUserId(name)).toMatch(USER_ID_RE);
  });

  it('gives the same id for the same name, so typing it again finds your coach', () => {
    expect(makeUserId('Jordan')).toBe('jordan');
    expect(makeUserId('  jordan ')).toBe('jordan');
    expect(makeUserId('名前')).toBe(makeUserId('名前'));
  });

  it('keeps a readable slug', () => {
    expect(makeUserId('José Ñúñez')).toBe('jose-nunez');
    expect(makeUserId("Mary-Jane O'Neil")).toBe('mary-jane-o-neil');
  });

  it('gives names with no Latin letters their own stable id', () => {
    expect(makeUserId('🚀🚀')).toMatch(/^user-[a-z0-9]{4}$/);
    expect(makeUserId('名前')).toMatch(/^user-[a-z0-9]{4}$/);
    expect(makeUserId('名前')).not.toBe(makeUserId('花子'));
    expect(makeUserId('x')).toMatch(/^x-[a-z0-9]{4}$/);
  });

  it('never goes past 63 characters', () => {
    expect(makeUserId('a'.repeat(200))).toHaveLength(63);
  });
});
