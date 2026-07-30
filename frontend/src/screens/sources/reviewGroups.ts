import type { EntitlementResource } from '../../api/types';

/*
 * Same-title collapse for the review list (FRG-UI-029 / FRG-SRC-011).
 *
 * Rows are grouped by the SERVER's `display_group_key` — the containment
 * merge of `matching_key(query_term())` (FRG-IMP-005) that reunites a
 * franchise split across title forms ("Series Vol. 3" / "THE FIRST ADVENTURE
 * OF SERIES", review-experience-2 design D4). Nothing here re-derives that
 * fold: a second, subtly different client fold is exactly how a large
 * same-title run would stop being one group. The client's only job is
 * bucketing, ordering, and summarising. The write-side sibling sweep keeps
 * acting on the narrower `group_key` — display-merging never widens it.
 *
 * Collapse is PRESENTATION, never a state filter: a group header carries the
 * mixed-status counts of its members and expanding always reaches every row's
 * full actions.
 */

/**
 * Groups at or above this size render collapsed by default (the large
 * same-title run a store's per-ordinal idioms produce).
 */
export const COLLAPSE_MIN_ROWS = 3;

export interface GroupCounts {
  new: number;
  matched: number;
  ignored: number;
  /** md5-duplicate copies (FRG-SRC-015) — parked, restorable, never grabbed. */
  duplicate: number;
  /** Rows whose download failed — actionable state a collapse must never hide. */
  failed: number;
}

export interface ReviewGroup {
  /** The server's fold — the group's identity and its stable render key. */
  key: string;
  /** Human label: the members' shared title prefix, else the first row's name. */
  title: string;
  rows: EntitlementResource[];
  /** The bundle every member came from, or null when they differ / are unknown. */
  bundle: string | null;
  counts: GroupCounts;
}

/**
 * One entry in the FLAT list the virtualizer indexes over. Headers and rows
 * share one index space on purpose: selection, the shift-range anchor and the
 * virtual window all address the same array, so they cannot drift apart.
 */
export type ReviewItem =
  | { kind: 'group-header'; key: string; group: ReviewGroup; collapsed: boolean }
  | {
      kind: 'row';
      key: string;
      entitlement: EntitlementResource;
      /** The group this row belongs to when it is inside an expanded one. */
      group: ReviewGroup | null;
    };

// Drop the punctuation/whitespace a cut lands on. Shared by the prefix fold
// below and the single-title fallback stripper.
function trimEdge(value: string): string {
  return value.replace(/[\s,:;(#.\-–—]+$/u, '').trim();
}

// Whole-token match only, so a title ending in "Casino" keeps its "no".
const DANGLING_WORD = /^(?:vol|volume|book|part|no|issue)$/i;

/**
 * Strip a trailing volume/issue suffix from ONE member's own title —
 * "Series Vol. 3" -> "Series", "Widget Book Two" -> "Widget", "Title #12" ->
 * "Title". Used only as the containment-merge fallback label (below): two
 * merged fold keys can share no literal prefix at all ("Series Vol. 3" vs
 * "THE FIRST ADVENTURE OF SERIES"), so the label falls back to one member's
 * own name rather than an empty/degenerate shared-prefix cut.
 */
function stripVolumeSuffix(title: string): string {
  const numberWord =
    '(?:one|two|three|four|five|six|seven|eight|nine|ten|\\d+[a-z]?)';
  const suffix = new RegExp(
    `[\\s,]*(?:vol\\.?|volume|book|part|no\\.?|issue|#)\\s*${numberWord}\\s*$`,
    'iu',
  );
  const stripped = trimEdge(title.replace(suffix, ''));
  return stripped || title.trim();
}

/**
 * Human label for a review group (FRG-UI-029): the members' longest shared
 * title prefix, trimmed to something readable. A containment-MERGED group
 * (members drawn from more than one exact `group_key`) can share no literal
 * prefix at all, since the merge reunites different title FORMS of one
 * franchise — that case falls back to the shortest member's own name with its
 * volume/issue suffix stripped, rather than the "first member, verbatim"
 * fallback an ordinary single-key group uses.
 */
function sharedTitle(rows: EntitlementResource[], merged: boolean): string {
  const names = rows.map((r) => r.human_name);
  let prefix = names[0] ?? '';
  for (const name of names.slice(1)) {
    let i = 0;
    while (
      i < prefix.length &&
      i < name.length &&
      prefix[i].toLowerCase() === name[i].toLowerCase()
    ) {
      i += 1;
    }
    prefix = prefix.slice(0, i);
    if (!prefix) break;
  }
  // Drop the punctuation/whitespace the cut lands on, then the dangling
  // volume-ordinal word the cut exposes: "Ember, Vol. " -> "Ember, Vol" ->
  // "Ember". The point is a label that reads like the series, not like the
  // longest string the members happen to share.
  const parts = trimEdge(prefix).split(/\s+/);
  while (parts.length > 1 && DANGLING_WORD.test(trimEdge(parts[parts.length - 1]))) {
    parts.pop();
  }
  const trimmed = trimEdge(parts.join(' '));
  if (trimmed.length >= 3) return trimmed;
  if (merged) {
    // No shared prefix to cut — pick the shortest member's own name (the
    // least likely to be padded with a subtitle) and strip ITS volume/issue
    // suffix, rather than naming a reunited franchise after an arbitrary
    // member's edition-specific title.
    const shortest = [...rows].sort(
      (a, b) => a.human_name.length - b.human_name.length,
    )[0];
    const stripped = stripVolumeSuffix(shortest?.human_name ?? '');
    if (stripped.length >= 3) return stripped;
  }
  // A one- or two-character sliver is noise, not a title — name the group after
  // its first member instead (still honest: the count says how many follow).
  return trimmed.length >= 3 ? trimmed : (names[0] ?? '');
}

function countStatuses(rows: EntitlementResource[]): GroupCounts {
  const counts: GroupCounts = {
    new: 0,
    matched: 0,
    ignored: 0,
    duplicate: 0,
    failed: 0,
  };
  for (const row of rows) {
    counts[row.review_status] += 1;
    if (row.download_state === 'failed') counts.failed += 1;
  }
  return counts;
}

/** Nulls-last numeric compare — shared shape for the two sort keys below. */
function compareNullableNumber(a: number | null, b: number | null): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return a - b;
}

/**
 * Numeric-aware issue-number compare ("2" before "10"), nulls last. Falls back
 * to a locale compare for non-numeric forms ("1.5", "1.MU") so those still
 * order deterministically relative to each other.
 */
function compareIssueNumber(a: string | null, b: string | null): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  const na = Number.parseFloat(a);
  const nb = Number.parseFloat(b);
  if (!Number.isNaN(na) && !Number.isNaN(nb) && na !== nb) return na - nb;
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
}

/**
 * Within-group order (FRG-UI-029 design D5): the server-computed
 * `(volume_ordinal, issue_number)` sort key, unknowns last, then name as the
 * final tiebreaker. The client sorts by these parsed fields only — it never
 * re-parses `human_name` itself (that would be a second, drifting fold).
 */
function compareGroupRows(a: EntitlementResource, b: EntitlementResource): number {
  const byOrdinal = compareNullableNumber(a.volume_ordinal, b.volume_ordinal);
  if (byOrdinal !== 0) return byOrdinal;
  const byIssue = compareIssueNumber(a.issue_number, b.issue_number);
  if (byIssue !== 0) return byIssue;
  return a.human_name.localeCompare(b.human_name);
}

function sharedBundle(rows: EntitlementResource[]): string | null {
  const first = rows[0]?.bundle_human_name ?? null;
  if (first === null) return null;
  return rows.every((r) => r.bundle_human_name === first) ? first : null;
}

function makeGroup(key: string, rows: EntitlementResource[]): ReviewGroup {
  // A containment-merged group draws from more than one exact `group_key`
  // (the sweep-key rows still carry, unmodified) — that's the ONLY signal the
  // client needs to know it is looking at a merge, since the server already
  // did the merging (`display_group_key`).
  const merged = new Set(rows.map((r) => r.group_key)).size > 1;
  const ordered = [...rows].sort(compareGroupRows);
  return {
    key,
    title: sharedTitle(rows, merged),
    rows: ordered,
    bundle: sharedBundle(rows),
    counts: countStatuses(rows),
  };
}

/**
 * Bucket already-filtered rows into the flat, virtualizable item list.
 *
 * Ordering: groups appear where their FIRST member appeared, and a group's
 * members are contiguous — so the list reads as "same-title runs, in the order
 * they first showed up" and an index span stays meaningful. A row whose
 * `display_group_key` (falling back to `group_key`) is empty (a title that
 * folds to nothing) never groups.
 *
 * Only groups of `COLLAPSE_MIN_ROWS` or more get a header; a pair of same-title
 * rows is not worth a chrome row, so those rows render plainly.
 */
export function buildReviewItems(
  rows: readonly EntitlementResource[],
  expandedGroups: ReadonlySet<string>,
  collapseMinRows: number = COLLAPSE_MIN_ROWS,
): { items: ReviewItem[]; groups: ReviewGroup[] } {
  type Slot = { key: string | null; rows: EntitlementResource[] };
  const slots: Slot[] = [];
  const byKey = new Map<string, Slot>();

  for (const row of rows) {
    // The DISPLAY fold (FRG-UI-029 D4): the server's containment merge of
    // `group_key` across title forms of one franchise. Bucketing on this
    // field rather than `group_key` directly is what reunites a renamed
    // series into one group; falling back to `group_key` keeps a fixture (or
    // an older payload) that never set it grouping exactly as before.
    const key = row.display_group_key || row.group_key || '';
    if (!key) {
      slots.push({ key: null, rows: [row] });
      continue;
    }
    const existing = byKey.get(key);
    if (existing) {
      existing.rows.push(row);
      continue;
    }
    const slot: Slot = { key, rows: [row] };
    byKey.set(key, slot);
    slots.push(slot);
  }

  const items: ReviewItem[] = [];
  const groups: ReviewGroup[] = [];
  for (const slot of slots) {
    if (slot.key !== null && slot.rows.length >= collapseMinRows) {
      const group = makeGroup(slot.key, slot.rows);
      groups.push(group);
      const collapsed = !expandedGroups.has(group.key);
      items.push({
        kind: 'group-header',
        key: `g:${group.key}`,
        group,
        collapsed,
      });
      if (!collapsed) {
        // `group.rows`, NOT `slot.rows`: `makeGroup` already sorted the
        // members into volume/issue order (D5) — rendering the arrival-order
        // slot here would silently discard that sort.
        for (const row of group.rows) {
          items.push({
            kind: 'row',
            key: `r:${row.id}`,
            entitlement: row,
            group,
          });
        }
      }
      continue;
    }
    for (const row of slot.rows) {
      items.push({ kind: 'row', key: `r:${row.id}`, entitlement: row, group: null });
    }
  }
  return { items, groups };
}

/** Every entitlement id an item stands for — a header stands for its members. */
export function itemIds(item: ReviewItem): number[] {
  return item.kind === 'row'
    ? [item.entitlement.id]
    : item.group.rows.map((r) => r.id);
}

/** Bundle names present in the current view, in first-appearance order. */
export function bundlesInView(
  rows: readonly EntitlementResource[],
): { name: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const row of rows) {
    const name = row.bundle_human_name;
    if (!name) continue;
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  return [...counts.entries()].map(([name, count]) => ({ name, count }));
}
