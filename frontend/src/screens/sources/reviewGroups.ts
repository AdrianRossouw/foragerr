import type { EntitlementResource } from '../../api/types';

/*
 * Same-title collapse for the review list (FRG-UI-029 / FRG-SRC-011).
 *
 * Rows are grouped by the SERVER's `group_key` — `matching_key(query_term())`,
 * the one shared title fold (FRG-IMP-005). Nothing here re-derives that fold:
 * a second, subtly different client fold is exactly how a large same-title
 * run would stop being one group. The client's only job is bucketing,
 * ordering, and summarising.
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

/** Longest shared prefix of the members' names, trimmed to something readable. */
function sharedTitle(rows: EntitlementResource[]): string {
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
  const trimEdge = (value: string) =>
    value.replace(/[\s,:;(#.\-–—]+$/u, '').trim();
  // Whole-token match only, so a title ending in "Casino" keeps its "no".
  const dangling = /^(?:vol|volume|book|part|no|issue)$/i;
  const parts = trimEdge(prefix).split(/\s+/);
  while (parts.length > 1 && dangling.test(trimEdge(parts[parts.length - 1]))) {
    parts.pop();
  }
  const trimmed = trimEdge(parts.join(' '));
  // A one- or two-character sliver is noise, not a title — name the group after
  // its first member instead (still honest: the count says how many follow).
  return trimmed.length >= 3 ? trimmed : (names[0] ?? '');
}

function countStatuses(rows: EntitlementResource[]): GroupCounts {
  const counts: GroupCounts = { new: 0, matched: 0, ignored: 0, failed: 0 };
  for (const row of rows) {
    counts[row.review_status] += 1;
    if (row.download_state === 'failed') counts.failed += 1;
  }
  return counts;
}

function sharedBundle(rows: EntitlementResource[]): string | null {
  const first = rows[0]?.bundle_human_name ?? null;
  if (first === null) return null;
  return rows.every((r) => r.bundle_human_name === first) ? first : null;
}

function makeGroup(key: string, rows: EntitlementResource[]): ReviewGroup {
  return {
    key,
    title: sharedTitle(rows),
    rows,
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
 * `group_key` is empty (a title that folds to nothing) never groups.
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
    const key = row.group_key || '';
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
        for (const row of slot.rows) {
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
