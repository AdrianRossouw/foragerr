import { describe, it, expect } from 'vitest';
import { formatBytes, formatAge, formatEta } from './format';

/*
 * FRG-UI-006/007 — the single formatting module. formatBytes is the one
 * canonical implementation (there is no second copy under utils/): it is
 * null/undefined-tolerant, renders 0 as "0 B", and guards non-finite input.
 */
describe('FRG-UI-006: format helpers', () => {
  it('FRG-UI-006 — formatBytes renders 0 as "0 B" and scales up units', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(1024)).toBe('1.0 KB');
    expect(formatBytes(42_000_000)).toBe('40.1 MB');
  });

  it('FRG-UI-006 — formatBytes returns an em dash for null/undefined and non-finite/negative input', () => {
    expect(formatBytes(null)).toBe('—');
    expect(formatBytes(undefined)).toBe('—');
    expect(formatBytes(Number.NaN)).toBe('—');
    expect(formatBytes(Number.POSITIVE_INFINITY)).toBe('—');
    expect(formatBytes(-1)).toBe('—');
  });

  it('FRG-UI-007 — formatAge and formatEta keep their Sonarr-style short forms', () => {
    expect(formatAge(3 * 3_600)).toBe('3h');
    expect(formatAge(2 * 86_400)).toBe('2d');
    expect(formatAge(null)).toBe('—');
    const now = Date.parse('2026-01-01T00:00:00Z');
    expect(formatEta('2026-01-01T00:04:00Z', now)).toBe('in 4m');
    expect(formatEta('2025-12-31T00:00:00Z', now)).toBe('—');
  });
});
