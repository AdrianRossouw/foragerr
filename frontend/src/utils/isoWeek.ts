/*
 * ISO-8601 week utilities (m4-pull-experience, design decision 2).
 *
 * Pure arithmetic over the ISO week rules (Thursday rule), NO date library — the
 * Calendar screen needs only week keys, day dates, and a range label, which is
 * ~40 lines of math not worth a new SOUP entry. The week/day math itself runs in
 * UTC (a stored release date is a plain date, so `weekDates`/`addWeeks`/
 * `weekRangeLabel` are timezone-independent by construction) and the keys match
 * the backend's `date.fromisocalendar` behaviour
 * (foragerr.pull.projection.current_week / week_date_range), including the
 * year-boundary cases (W52/W53 -> W01). The ONE spot that must read local time
 * is "what day is it for this viewer" (`currentIsoWeek`'s default): near a week
 * boundary a viewer far from UTC is in a different calendar day than UTC, so the
 * default week is derived from the LOCAL calendar date before the UTC ISO math
 * runs on it.
 */

const MS_PER_DAY = 86_400_000;
const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
] as const;
const WEEK_RE = /^(\d{4})-W(\d{2})$/;

/** Weekday of a UTC date as Mon=0 … Sun=6 (JS getUTCDay is Sun=0). */
function isoDow(date: Date): number {
  return (date.getUTCDay() + 6) % 7;
}

/** The Monday (UTC midnight) of the ISO week containing `date`. */
function mondayOf(date: Date): Date {
  const d = new Date(
    Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()),
  );
  d.setUTCDate(d.getUTCDate() - isoDow(d));
  return d;
}

/** The `YYYY-Www` key of the ISO week containing a UTC-midnight `date`. */
function weekKeyOf(date: Date): string {
  const monday = mondayOf(date);
  // The Thursday of this ISO week decides the ISO YEAR (Thursday rule): a week
  // belongs to whichever year holds its Thursday, so late-Dec / early-Jan weeks
  // resolve to the ISO year rather than the calendar year.
  const thursday = new Date(monday.getTime() + 3 * MS_PER_DAY);
  const isoYear = thursday.getUTCFullYear();
  // Week 1 is the week containing Jan 4 (equivalently, the year's first Thursday).
  const week1Monday = mondayOf(new Date(Date.UTC(isoYear, 0, 4)));
  const week =
    1 + Math.round((monday.getTime() - week1Monday.getTime()) / (7 * MS_PER_DAY));
  return `${isoYear}-W${String(week).padStart(2, '0')}`;
}

function parseWeek(week: string): { year: number; week: number } {
  const match = WEEK_RE.exec(week);
  if (!match) {
    throw new Error(
      `malformed ISO week ${JSON.stringify(week)}; expected "YYYY-Www"`,
    );
  }
  return { year: Number(match[1]), week: Number(match[2]) };
}

/** The Monday (UTC midnight) of an ISO year-week key. */
function weekMonday(week: string): Date {
  const { year, week: weekNumber } = parseWeek(week);
  const week1Monday = mondayOf(new Date(Date.UTC(year, 0, 4)));
  return new Date(week1Monday.getTime() + (weekNumber - 1) * 7 * MS_PER_DAY);
}

/** `YYYY-MM-DD` for a UTC date — the store-date key the pull rows carry. */
export function isoDateKey(date: Date): string {
  const y = date.getUTCFullYear();
  const m = String(date.getUTCMonth() + 1).padStart(2, '0');
  const d = String(date.getUTCDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/**
 * The ISO year-week key (e.g. `"2026-W27"`) for `asOf` (default: now). "Today"
 * is the viewer's LOCAL calendar day: near a week boundary a user far from UTC
 * is on a different date than UTC, and the default Calendar week / Today badge
 * must follow the day they are actually living in. We read `asOf`'s LOCAL
 * year/month/day and then run the pure-UTC ISO math on that calendar date (the
 * week key itself is date-only, so the arithmetic stays timezone-independent).
 */
export function currentIsoWeek(asOf: Date = new Date()): string {
  const utc = new Date(
    Date.UTC(asOf.getFullYear(), asOf.getMonth(), asOf.getDate()),
  );
  return weekKeyOf(utc);
}

/**
 * Shift a week key by `n` whole weeks (may be negative), normalising across year
 * boundaries — e.g. `addWeeks("2020-W53", 1) === "2021-W01"` and
 * `addWeeks("2019-W52", 1) === "2020-W01"` (2019 has no W53).
 */
export function addWeeks(week: string, n: number): string {
  const monday = weekMonday(week);
  return weekKeyOf(new Date(monday.getTime() + n * 7 * MS_PER_DAY));
}

/** The seven UTC-midnight day Dates (Mon…Sun) of an ISO week. */
export function weekDates(week: string): Date[] {
  const monday = weekMonday(week);
  return Array.from(
    { length: 7 },
    (_, i) => new Date(monday.getTime() + i * MS_PER_DAY),
  );
}

/**
 * A human range label for the toolbar, e.g. `"Jun 29 – Jul 5, 2026"`. The year
 * is taken from the Sunday so a week straddling New Year reads with the later
 * year (matching how the ISO key resolves).
 */
export function weekRangeLabel(week: string): string {
  const days = weekDates(week);
  const start = days[0];
  const end = days[6];
  const startPart = `${MONTHS[start.getUTCMonth()]} ${start.getUTCDate()}`;
  const endPart = `${MONTHS[end.getUTCMonth()]} ${end.getUTCDate()}`;
  return `${startPart} – ${endPart}, ${end.getUTCFullYear()}`;
}
