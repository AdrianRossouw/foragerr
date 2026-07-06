import { describe, it, expect } from 'vitest';
import { formatBytes, formatAge, formatEta, formatDate } from './format';

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

  /*
   * FRG-API-014 — the backend's naive-UTC `utcnow()` (no tzinfo) serializes
   * via Pydantic v2 as an offset-less ISO string ("2026-07-06T03:00:00", no
   * 'Z'). `Date.parse`/`new Date(...)` treat that as LOCAL time, so a UTC+2
   * viewer would see next-run/disabled-until countdowns 2h in the past. Both
   * formatEta and formatDate must parse an offset-less datetime as UTC —
   * proven here by a fixed comparison against the Z-suffixed equivalent,
   * which parses identically regardless of the test runner's own timezone.
   */
  it('FRG-API-014 — formatEta parses an offset-less backend datetime as UTC, not local time', () => {
    const now = Date.parse('2026-07-06T03:00:00Z');
    expect(formatEta('2026-07-06T03:04:00', now)).toBe('in 4m');
    expect(formatEta('2026-07-06T03:04:00', now)).toBe(
      formatEta('2026-07-06T03:04:00Z', now),
    );
  });

  it('FRG-API-014 — formatEta leaves an already offset/Z-suffixed datetime unchanged', () => {
    const now = Date.parse('2026-07-06T03:00:00Z');
    // "05:04:00+02:00" is the same instant as "03:04:00Z" — 4 minutes ahead of `now`.
    expect(formatEta('2026-07-06T05:04:00+02:00', now)).toBe('in 4m');
    expect(formatEta('2026-07-06T05:04:00+02:00', now)).toBe(
      formatEta('2026-07-06T03:04:00Z', now),
    );
  });

  it('FRG-API-014 — formatDate parses an offset-less backend datetime as UTC, not local time', () => {
    expect(formatDate('2026-07-06T23:30:00')).toBe(
      formatDate('2026-07-06T23:30:00Z'),
    );
  });

  it('FRG-API-014 — formatDate is unchanged for a plain date (no time component)', () => {
    expect(formatDate('2026-07-06')).toBe(formatDate('2026-07-06T00:00:00Z'));
  });
});
