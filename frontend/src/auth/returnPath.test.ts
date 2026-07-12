import { describe, it, expect } from 'vitest';
import { safeReturnPath } from './returnPath';

// FRG-AUTH-002: the login `return` param is attacker-controllable; validate it
// resolves same-origin before it reaches navigate() (a crash/open-redirect
// surface otherwise).
describe('safeReturnPath (FRG-AUTH-002)', () => {
  it('keeps genuine same-origin relative paths', () => {
    expect(safeReturnPath('/queue')).toBe('/queue');
    expect(safeReturnPath('/series/42?tab=issues')).toBe('/series/42?tab=issues');
  });

  it('falls back to / for empty / missing input', () => {
    expect(safeReturnPath(null)).toBe('/');
    expect(safeReturnPath(undefined)).toBe('/');
    expect(safeReturnPath('')).toBe('/');
  });

  it('rejects protocol-relative and absolute URLs', () => {
    expect(safeReturnPath('//evil.com')).toBe('/');
    expect(safeReturnPath('https://evil.com/x')).toBe('/');
    expect(safeReturnPath('http://evil.com')).toBe('/');
  });

  it('rejects crafted values a substring guard would have passed', () => {
    // backslash normalizes to slash for special schemes -> cross-origin
    expect(safeReturnPath('/\\evil.com')).toBe('/');
    // embedded tab is stripped during URL parsing -> //evil.com
    expect(safeReturnPath('/\t/evil.com')).toBe('/');
    expect(safeReturnPath('/\n/evil.com')).toBe('/');
  });
});
