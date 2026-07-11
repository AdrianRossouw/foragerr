import { describe, it, expect } from 'vitest';
import {
  addWeeks,
  currentIsoWeek,
  isoDateKey,
  weekDates,
  weekRangeLabel,
} from './isoWeek';

/**
 * ISO-8601 week math (design decision 2). Pinned against real year-boundary
 * edge cases — the same cases the backend's `date.fromisocalendar` handling
 * must agree with (projection.py): 2020 has an ISO week 53, 2019 does not, and
 * a Jan-1 date can belong to the previous ISO year.
 *
 * All fixture dates are built with `Date.UTC(...)` so the assertions are
 * timezone-independent (the utilities read UTC components).
 */
const utc = (y: number, m: number, d: number) => new Date(Date.UTC(y, m - 1, d));

describe('isoWeek', () => {
  it('currentIsoWeek resolves a mid-year date to its ISO week', () => {
    // 2026-07-01 is the Wednesday of ISO week 27 of 2026.
    expect(currentIsoWeek(utc(2026, 7, 1))).toBe('2026-W27');
  });

  it('currentIsoWeek pads the week number to two digits', () => {
    expect(currentIsoWeek(utc(2026, 1, 5))).toBe('2026-W02');
  });

  it('currentIsoWeek honours the Thursday rule across a year boundary', () => {
    // 2020 is a long ISO year (53 weeks); its W53 spills into January 2021.
    expect(currentIsoWeek(utc(2020, 12, 31))).toBe('2020-W53');
    // Jan 1 2021 (a Friday) still belongs to 2020-W53, not 2021-W01.
    expect(currentIsoWeek(utc(2021, 1, 1))).toBe('2020-W53');
    // Jan 4 2021 (a Monday) opens 2021-W01.
    expect(currentIsoWeek(utc(2021, 1, 4))).toBe('2021-W01');
  });

  it('addWeeks rolls W53 forward into the next ISO year', () => {
    expect(addWeeks('2020-W52', 1)).toBe('2020-W53');
    expect(addWeeks('2020-W53', 1)).toBe('2021-W01');
  });

  it('addWeeks skips a non-existent W53 (2019 is a short ISO year)', () => {
    // 2019 has only 52 ISO weeks, so W52 + 1 wraps straight to 2020-W01.
    expect(addWeeks('2019-W52', 1)).toBe('2020-W01');
  });

  it('addWeeks steps backward across a year boundary', () => {
    expect(addWeeks('2021-W01', -1)).toBe('2020-W53');
    expect(addWeeks('2020-W01', -1)).toBe('2019-W52');
  });

  it('weekDates returns the seven Mon…Sun UTC day keys of a week', () => {
    const keys = weekDates('2020-W53').map(isoDateKey);
    expect(keys).toEqual([
      '2020-12-28', // Monday
      '2020-12-29',
      '2020-12-30',
      '2020-12-31',
      '2021-01-01',
      '2021-01-02',
      '2021-01-03', // Sunday
    ]);
  });

  it('weekRangeLabel formats a cross-month, cross-year span with the later year', () => {
    expect(weekRangeLabel('2020-W53')).toBe('Dec 28 – Jan 3, 2021');
    expect(weekRangeLabel('2026-W27')).toBe('Jun 29 – Jul 5, 2026');
  });
});
