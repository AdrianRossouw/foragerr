import { describe, it, expect } from 'vitest';
import { buildReviewItems, itemIds, bundlesInView } from './reviewGroups';
import type { ReviewItem } from './reviewGroups';
import type { EntitlementResource } from '../../api/types';

/** Entitlement ids of the flat item list's ROW entries, in list order. */
function rowIdsOf(items: ReviewItem[]): number[] {
  const ids: number[] = [];
  for (const item of items) {
    if (item.kind === 'row') ids.push(item.entitlement.id);
  }
  return ids;
}

/*
 * FRG-UI-029 — the same-title collapse's pure core, tested directly rather than
 * through the screen: the group LABEL (a shared prefix cut to something that
 * reads like a series) and the flat item array the virtualizer, the selection
 * and the shift-range all index over.
 */

function ent(
  o: Partial<EntitlementResource> & Pick<EntitlementResource, 'id'>,
): EntitlementResource {
  const groupKey = o.group_key ?? `item-${o.id}`;
  return {
    source_id: 5,
    machine_name: `m-${o.id}`,
    human_name: `Item ${o.id}`,
    publisher: 'Image',
    bundle_human_name: null,
    group_key: groupKey,
    // Defaults to `group_key` (unmerged, review-experience-2 contract) — a
    // test that wants a containment-merged group sets this explicitly.
    display_group_key: o.display_group_key ?? groupKey,
    classification: 'comic',
    classified_via: null,
    review_status: 'new',
    download_state: null,
    download_error: null,
    preferred_format: 'CBZ',
    file_size: 1000,
    filename: `item-${o.id}.cbz`,
    proposed_series_id: null,
    matched_series_id: null,
    proposed_match: null,
    duplicate_of: null,
    duplicate_count: 0,
    duplicate_bundles: [],
    volume_ordinal: null,
    issue_number: null,
    ...o,
  };
}

/** Build one group of same-key rows and read back its rendered title. */
function titleOf(names: string[]): string {
  const rows = names.map((human_name, i) =>
    ent({ id: 500 + i, human_name, group_key: 'k' }),
  );
  const { groups } = buildReviewItems(rows, new Set());
  expect(groups).toHaveLength(1);
  return groups[0].title;
}

describe('FRG-UI-029: sharedTitle', () => {
  it('FRG-UI-029 — trims the punctuation and the dangling volume word the prefix cut exposes', () => {
    // "Ember, Vol. " -> "Ember, Vol" -> "Ember": the label reads like the
    // series, not like the longest string the members happen to share.
    expect(titleOf(['Ember, Vol. 1', 'Ember, Vol. 2', 'Ember, Vol. 3'])).toBe(
      'Ember',
    );
    expect(titleOf(['Vane Book One', 'Vane Book Two', 'Vane Book Three'])).toBe(
      'Vane',
    );
    expect(
      titleOf(['Driftwood #1', 'Driftwood #2', 'Driftwood #3']),
    ).toBe('Driftwood');
    expect(
      titleOf(['Glasswing - Part 1', 'Glasswing - Part 2', 'Glasswing - Part 3']),
    ).toBe('Glasswing');
  });

  it('FRG-UI-029 — a dangling word is trimmed only as a WHOLE token (the "Casino" case)', () => {
    // The prefix ends in "Casino", whose last two letters are the dangling
    // word "no" — a substring match would maul the title into "Casi".
    expect(
      titleOf(['Casino Royale 1', 'Casino Royale 2', 'Casino Royale 3']),
    ).toBe('Casino Royale');
    expect(titleOf(['Casino, One', 'Casino, Two', 'Casino, Three'])).toBe(
      'Casino',
    );
  });

  it('FRG-UI-029 — the trim never eats the whole label: the last token survives', () => {
    // The only token IS a dangling word, so the loop must stop rather than
    // leaving an empty title.
    expect(titleOf(['Vol 1', 'Vol 2', 'Vol 3'])).toBe('Vol');
    // …and when the surviving token is itself a sliver, the sub-3-character
    // fallback catches it and names the group after its first member.
    expect(titleOf(['No 1', 'No 2', 'No 3'])).toBe('No 1');
  });

  it('FRG-UI-029 — a sub-3-character sliver falls back to the first member name', () => {
    // The shared prefix is "A" — noise, not a title. The group is named after
    // its first member instead (the count still says how many follow).
    expect(titleOf(['Aster', 'Amber Vault', 'Alcove Nine'])).toBe('Aster');
    // Same rule when the members share nothing at all (empty prefix).
    expect(titleOf(['Rook', 'Vane', 'Driftwood'])).toBe('Rook');
  });
});

describe('FRG-UI-029: buildReviewItems', () => {
  it('FRG-UI-029 — an empty group_key NEVER groups, however many rows share it', () => {
    const rows = [
      ent({ id: 1, group_key: '' }),
      ent({ id: 2, group_key: '' }),
      ent({ id: 3, group_key: '' }),
      ent({ id: 4, group_key: '' }),
    ];
    const { items, groups } = buildReviewItems(rows, new Set());

    expect(groups).toHaveLength(0);
    expect(items).toHaveLength(4);
    expect(items.every((i) => i.kind === 'row')).toBe(true);
    expect(items.map((i) => i.key)).toEqual(['r:1', 'r:2', 'r:3', 'r:4']);
  });

  it('FRG-UI-029 — fewer than COLLAPSE_MIN_ROWS rows render plainly, with no header', () => {
    const pair = [
      ent({ id: 10, group_key: 'vane' }),
      ent({ id: 11, group_key: 'vane' }),
    ];
    const { items, groups } = buildReviewItems(pair, new Set());

    expect(groups).toHaveLength(0);
    expect(items.map((i) => i.key)).toEqual(['r:10', 'r:11']);
    // A plain row belongs to no group, so nothing renders it as grouped.
    expect(items.every((i) => i.kind === 'row' && i.group === null)).toBe(true);
  });

  it('FRG-UI-029 — a group collapses unless its key is in expandedGroups', () => {
    const rows = [
      ent({ id: 20, human_name: 'Ember, Vol. 1', group_key: 'ember' }),
      ent({ id: 21, human_name: 'Ember, Vol. 2', group_key: 'ember' }),
      ent({ id: 22, human_name: 'Ember, Vol. 3', group_key: 'ember' }),
      ent({ id: 30, human_name: 'Driftwood' }),
    ];

    // Collapsed: the header stands alone where its FIRST member appeared, and
    // the unrelated row keeps its place after it.
    const collapsed = buildReviewItems(rows, new Set());
    expect(collapsed.items.map((i) => i.key)).toEqual(['g:ember', 'r:30']);
    expect(collapsed.items[0]).toMatchObject({
      kind: 'group-header',
      collapsed: true,
    });
    // Collapse is presentation, never a selection filter: the header stands
    // for every row folded inside it.
    expect(itemIds(collapsed.items[0])).toEqual([20, 21, 22]);

    // Expanded: the members follow their header, contiguously and in order.
    const expanded = buildReviewItems(rows, new Set(['ember']));
    expect(expanded.items.map((i) => i.key)).toEqual([
      'g:ember',
      'r:20',
      'r:21',
      'r:22',
      'r:30',
    ]);
    expect(expanded.items[0]).toMatchObject({ collapsed: false });
    // A member row carries its group, which is what renders it as indented.
    expect(expanded.items[1]).toMatchObject({ kind: 'row' });
    expect(
      expanded.items[1].kind === 'row' ? expanded.items[1].group?.key : null,
    ).toBe('ember');
    // …and an unrelated expandedGroups entry changes nothing.
    expect(
      buildReviewItems(rows, new Set(['nope'])).items.map((i) => i.key),
    ).toEqual(['g:ember', 'r:30']);
  });

  it('FRG-UI-029 — a group appears where its first member did, and its counts/bundle summarise the members', () => {
    const rows = [
      ent({ id: 40, human_name: 'Before' }),
      ent({ id: 41, human_name: 'Ember, Vol. 1', group_key: 'ember', bundle_human_name: 'Synthetic Firsts' }),
      ent({ id: 42, human_name: 'Interleaved' }),
      ent({
        id: 43,
        human_name: 'Ember, Vol. 2',
        group_key: 'ember',
        review_status: 'matched',
        bundle_human_name: 'Synthetic Firsts',
      }),
      ent({
        id: 44,
        human_name: 'Ember, Vol. 3',
        group_key: 'ember',
        download_state: 'failed',
        bundle_human_name: 'Synthetic Firsts',
      }),
    ];
    const { items, groups } = buildReviewItems(rows, new Set());

    // The group takes the slot of row 41 — the later members move up to it.
    expect(items.map((i) => i.key)).toEqual(['r:40', 'g:ember', 'r:42']);
    expect(groups[0].rows.map((r) => r.id)).toEqual([41, 43, 44]);
    expect(groups[0].counts).toEqual({
      new: 2,
      matched: 1,
      ignored: 0,
      duplicate: 0,
      failed: 1,
    });
    // One shared bundle names itself; a mixed group names none.
    expect(groups[0].bundle).toBe('Synthetic Firsts');
    const mixed = buildReviewItems(
      rows.map((r) =>
        r.id === 44 ? { ...r, bundle_human_name: 'Other Bundle' } : r,
      ),
      new Set(),
    );
    expect(mixed.groups[0].bundle).toBeNull();
  });

  it('FRG-UI-029 — the collapse threshold is a parameter, so a caller can prove the boundary', () => {
    const pair = [
      ent({ id: 50, group_key: 'vane' }),
      ent({ id: 51, group_key: 'vane' }),
    ];
    expect(buildReviewItems(pair, new Set(), 2).items.map((i) => i.key)).toEqual(
      ['g:vane'],
    );
  });
});

describe('FRG-UI-029 (review-experience-2): containment-merged display groups', () => {
  it('FRG-UI-029 — rows with different group_key but the same display_group_key bucket into ONE group', () => {
    const rows = [
      ent({ id: 70, human_name: 'Series Vol. 3', group_key: 'series-vol-3', display_group_key: 'series' }),
      ent({ id: 71, human_name: 'THE FIRST ADVENTURE OF SERIES', group_key: 'the-first-adventure-of-series', display_group_key: 'series' }),
      ent({ id: 72, human_name: 'Series Vol. 5', group_key: 'series-vol-5', display_group_key: 'series' }),
    ];
    const { items, groups } = buildReviewItems(rows, new Set());

    expect(groups).toHaveLength(1);
    expect(items.map((i) => i.key)).toEqual(['g:series']);
    expect(groups[0].rows.map((r) => r.id).sort()).toEqual([70, 71, 72]);
  });

  it('FRG-UI-029 — a merged group with no shared prefix labels itself from the shortest member, suffix stripped', () => {
    const rows = [
      ent({ id: 80, human_name: 'Series Vol. 3', group_key: 'a', display_group_key: 'merged' }),
      ent({ id: 81, human_name: 'THE FIRST ADVENTURE OF SERIES', group_key: 'b', display_group_key: 'merged' }),
      ent({ id: 82, human_name: 'Series Vol. 5', group_key: 'a', display_group_key: 'merged' }),
    ];
    const { groups } = buildReviewItems(rows, new Set());
    // "Series Vol. 3" (shortest) stripped of its volume suffix -> "Series" —
    // never the empty/degenerate cut an ordinary shared-prefix fold would hit.
    expect(groups[0].title).toBe('Series');
  });

  it('FRG-UI-029 — an UNMERGED group (single group_key) keeps the ordinary first-member fallback', () => {
    // Same degenerate-prefix shape as the merged case, but every row shares
    // ONE group_key — the containment-merge fallback must not fire here.
    const rows = [
      ent({ id: 90, human_name: 'Rook', group_key: 'k' }),
      ent({ id: 91, human_name: 'Vane', group_key: 'k' }),
      ent({ id: 92, human_name: 'Driftwood', group_key: 'k' }),
    ];
    const { groups } = buildReviewItems(rows, new Set());
    expect(groups[0].title).toBe('Rook');
  });

  it('FRG-UI-029 (design D5) — members order by volume_ordinal then numeric-aware issue_number, unknowns last', () => {
    const rows = [
      ent({ id: 100, human_name: 'Series #10', group_key: 'k', volume_ordinal: null, issue_number: '10' }),
      ent({ id: 101, human_name: 'Series Vol. 2', group_key: 'k', volume_ordinal: 2, issue_number: null }),
      ent({ id: 102, human_name: 'Series #2', group_key: 'k', volume_ordinal: null, issue_number: '2' }),
      ent({ id: 103, human_name: 'Series Vol. 1', group_key: 'k', volume_ordinal: 1, issue_number: null }),
    ];
    const { groups } = buildReviewItems(rows, new Set());
    // ordinal 1, ordinal 2, then the unordinalled issues (numeric-aware: 2
    // before 10), never a lexical "10" < "2" mistake.
    expect(groups[0].rows.map((r) => r.id)).toEqual([103, 101, 102, 100]);

    // The expanded item list renders in that SAME sorted order, not arrival
    // order — buildReviewItems must read the sorted `group.rows`, not the
    // arrival-order slot, when it expands a group.
    const expanded = buildReviewItems(rows, new Set(['k']));
    expect(rowIdsOf(expanded.items)).toEqual([103, 101, 102, 100]);
  });

  it('FRG-UI-029 (design D5) — a sub-threshold same-key run is ordered by the SAME comparator', () => {
    // Two rows share a title but never earn a header. Within-key order is a
    // property of the key, not of whether the run grew big enough for chrome —
    // otherwise the pair silently re-sorts the day a third row arrives.
    const pair = [
      ent({ id: 200, human_name: 'Series Vol. 2', group_key: 'k', volume_ordinal: 2 }),
      ent({ id: 201, human_name: 'Series Vol. 1', group_key: 'k', volume_ordinal: 1 }),
    ];
    const { items, groups } = buildReviewItems(pair, new Set());

    expect(groups).toHaveLength(0); // still no header
    expect(rowIdsOf(items)).toEqual([201, 200]);
    // …and the order it renders in is the order it keeps once a third arrival
    // pushes the run over the threshold.
    const grown = buildReviewItems(
      [
        ...pair,
        ent({ id: 202, human_name: 'Series Vol. 3', group_key: 'k', volume_ordinal: 3 }),
      ],
      new Set(['k']),
    );
    expect(rowIdsOf(grown.items)).toEqual([201, 200, 202]);
  });
});

describe('FRG-SRC-011: bundlesInView', () => {
  it('FRG-SRC-011 — counts each bundle in first-appearance order, skipping unnamed rows', () => {
    const rows = [
      ent({ id: 60, bundle_human_name: 'Driftwood Bundle' }),
      ent({ id: 61, bundle_human_name: null }),
      ent({ id: 62, bundle_human_name: 'Synthetic Firsts' }),
      ent({ id: 63, bundle_human_name: 'Driftwood Bundle' }),
    ];
    expect(bundlesInView(rows)).toEqual([
      { name: 'Driftwood Bundle', count: 2 },
      { name: 'Synthetic Firsts', count: 1 },
    ]);
  });
});
