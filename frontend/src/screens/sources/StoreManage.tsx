import { useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { observeElementRect, useVirtualizer } from '@tanstack/react-virtual';
import { Menu } from '../../components/Menu';
import { SegmentedControl } from '../../components/SegmentedControl';
import { Toggle } from '../../components/Toggle';
import { ComicVineBudgetChip } from '../../components/ComicVineBudget';
import { EntitlementRow } from './EntitlementRow';
import { EntitlementGroupHeader } from './EntitlementGroupHeader';
import type { PickedCandidate } from './EntitlementSearch';
import {
  bundlesInView,
  buildReviewItems,
  itemIds,
  type ReviewGroup,
} from './reviewGroups';
import { useSeriesIndex, useWatchedCommand } from '../../api/hooks';
import {
  useBulkEntitlements,
  useDisconnectSource,
  useEntitlements,
  useRecomputeProposals,
  useSyncSource,
  useUpdateSource,
} from '../../api/sourceHooks';
import { queryKeys } from '../../api/queryKeys';
import type { EntitlementResource, StoreSourceResource } from '../../api/types';
import styles from './sources.module.css';

/**
 * The review scopes (FRG-UI-029). `other` is the non-comic scope: a filter
 * beside the review statuses, NOT a reveal mixed into one of them — see
 * `visible` for why that distinction is the whole point.
 */
type Filter = 'all' | 'new' | 'matched' | 'ignored' | 'duplicate' | 'other';

/**
 * Every scope, in the order the filter row offers them. Named once so the
 * counts are derived by MAPPING over it rather than by a second traversal that
 * could disagree with `rowsInScope`.
 */
const FILTERS: readonly Filter[] = [
  'all',
  'new',
  'matched',
  'ignored',
  'duplicate',
  'other',
];

/** One row's failure inside a bulk accept, named for the operator. */
interface BulkFailure {
  id: number;
  name: string;
  message: string;
}

/**
 * Starting height guess for one collapsed review row (FRG-UI-029). Every
 * mounted row is measured for real (`measureElement`), so this only shapes the
 * scrollbar before a row has been seen — and doubles as the fallback when the
 * environment reports no layout at all (jsdom), keeping the windowing math
 * coherent under test.
 */
const ROW_ESTIMATE_PX = 78;

/**
 * Stable stand-in for "no entitlements loaded yet". A fresh `[]` per render
 * would give the scoping memo below a new dependency identity every time and
 * defeat the whole grouping cache while the query is in flight.
 */
const NO_ENTITLEMENTS: EntitlementResource[] = [];

/**
 * Viewport height assumed when the scroll container reports none, IN TESTS ONLY.
 * A zero-height measurement means "this environment did no layout" (jsdom) — the
 * virtualizer's own answer to a zero viewport is to render NOTHING, which would
 * turn a layout-less environment into a silently empty list. Falling back to a
 * nominal viewport keeps the list windowing coherently under test.
 *
 * In a real browser a zero-height scroll container is a LAYOUT BUG (a collapsed
 * flex parent, a hidden ancestor), and absorbing it here would hide that bug
 * behind a list that renders 720px of rows into a container nobody can see. So
 * the fallback is scoped to the test environment and a real zero height is
 * passed through, where it surfaces as a visibly empty list.
 */
const VIEWPORT_FALLBACK_PX = 720;

/** True only under vitest, where jsdom reports no layout at all. */
const LAYOUTLESS_ENV = import.meta.env.MODE === 'test';

/** Starting height guess for a collapse-group header (measured for real after). */
const GROUP_HEADER_ESTIMATE_PX = 62;

/**
 * The rows one filter scope shows (FRG-UI-029) — the single definition the
 * list, the counts, the select-all and the selection narrowing all read from.
 *
 * Non-comic is a SCOPE, not a reveal. The reveal it replaces stopped EXCLUDING
 * `other` rows, so they arrived mixed into whichever status scope was on
 * screen; a selection built there spanned classifications and came back mostly
 * refused per row, which reads as an action that only half worked. Here the
 * non-comic scope holds exactly the non-comic rows and every other scope holds
 * exactly comic rows — `all` additionally excluding `duplicate` (FRG-SRC-015:
 * a parked copy was already reviewed once as its canonical row, so the
 * Duplicates filter is its only home).
 *
 * The scope model is ONE-DIMENSIONAL on purpose: `other` is not sub-divided by
 * review status, so Ignored and Duplicates are comic-only BY CONSTRUCTION and a
 * parked non-comic row is reachable only under Non-comic — which is where it
 * appears. A status sub-axis inside the non-comic scope would buy a cleaner
 * bulk selection at the cost of two axes to reason about; the bulk bar states
 * its applicable count instead (see `applicable` below).
 */
function rowsInScope(
  rows: readonly EntitlementResource[],
  filter: Filter,
): EntitlementResource[] {
  if (filter === 'other') {
    return rows.filter((e) => e.classification === 'other');
  }
  const comics = rows.filter((e) => e.classification === 'comic');
  return filter === 'all'
    ? comics.filter((e) => e.review_status !== 'duplicate')
    : comics.filter((e) => e.review_status === filter);
}

/**
 * How each bulk action names itself: in its button while the request is in
 * flight, in its result note, and in the failure panel.
 */
const BULK_VERBS = {
  accept: { note: 'Accepted', past: 'accepted', pending: 'Accepting…' },
  ignore: { note: 'Ignored', past: 'ignored', pending: 'Ignoring…' },
  restore: { note: 'Restored', past: 'restored', pending: 'Restoring…' },
  mark_non_comic: {
    note: 'Marked non-comic',
    past: 'marked non-comic',
    pending: 'Marking…',
  },
  mark_comic: {
    note: 'Marked comic',
    past: 'marked comic',
    pending: 'Marking…',
  },
} as const;

type BulkAction = keyof typeof BULK_VERBS;

/**
 * Whether one row satisfies an action's server-side per-row precondition —
 * the client-side mirror of the refusals `review.py` raises.
 *
 * It exists so the bulk bar can say how much of a selection an action can
 * actually apply to BEFORE the click (see `applicable`). A scope holds one
 * classification but any mix of review statuses, so "select all 73 → Restore"
 * legitimately reaches rows restore refuses; the count is what turns that from
 * an action that half-worked into a stated one. It is not a gate: the request
 * still carries the whole in-scope selection and the server's per-row errors
 * remain the authority (a row can change under us between render and click).
 */
const BULK_APPLIES: Record<BulkAction, (row: EntitlementResource) => boolean> = {
  accept: (row) => row.review_status === 'new',
  // Ignore takes any row in any state and is idempotent — there is no state it
  // refuses, so its count can never differ from the selection size.
  ignore: () => true,
  restore: (row) =>
    row.review_status === 'ignored' || row.review_status === 'duplicate',
  mark_non_comic: (row) => row.review_status === 'new',
  mark_comic: (row) => row.review_status === 'new',
};

/**
 * Connected-store manage view (FRG-UI-029): account bar (auto-sync toggle, Sync
 * now, Disconnect), the publisher-rules editor (FRG-SRC-012), the count line +
 * All/New/Matched/Ignored/Duplicates/Non-comic filter segments, and the
 * reviewable entitlement list. "All" and the pending counts exclude `duplicate`
 * rows (FRG-SRC-015) — a parked copy was already reviewed once as its canonical
 * row, so the Duplicates filter is its only home.
 *
 * The list is the at-scale surface (the dogfood first sync is 1,318 rows): it
 * virtualizes, same-title runs fold into expandable groups keyed by the
 * server's shared title fold, and a selection can be built by select-all, by
 * shift-range (FRG-UI-025), by whole group, or by whole bundle — then applied
 * in ONE bulk accept where each row contributes its own proposal
 * (FRG-SRC-011). Selection is id-based over the filtered list, so it spans
 * items the virtual window has scrolled past and rows hidden inside a collapsed
 * group — and never a row outside the active scope.
 */
export function StoreManage({ source }: { source: StoreSourceResource }) {
  const entitlementsQuery = useEntitlements(source.id);
  const seriesQuery = useSeriesIndex();
  const librarySeries = seriesQuery.data ?? [];

  const [filter, setFilter] = useState<Filter>('all');
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set());
  // The shift-range anchor is a review-ITEM key ("r:12" / "g:ember"), not a row
  // id: headers and rows share one index space, so the anchor must too.
  const [anchorKey, setAnchorKey] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(new Set());
  // Which rows have their ComicVine search panel open (FRG-UI-039). Held HERE,
  // beside `expanded`, and not inside the row: the list is virtualized, so a row
  // scrolled out of the overscan unmounts — component-local panel state would be
  // destroyed by scrolling past it. Owned by the list, it survives and the row
  // re-mounts with its panel still open.
  const [searchOpen, setSearchOpen] = useState<ReadonlySet<number>>(new Set());
  // Which GROUP headers have their search/match picker open (FRG-UI-043), keyed
  // by group_key. List-owned for the same reason the per-row set is: a collapsed
  // header scrolled out of the virtual window would otherwise lose it.
  const [groupSearchOpen, setGroupSearchOpen] = useState<ReadonlySet<string>>(
    new Set(),
  );
  const [expandedGroups, setExpandedGroups] = useState<ReadonlySet<string>>(
    new Set(),
  );
  const [bulkNote, setBulkNote] = useState<string | null>(null);
  const [failures, setFailures] = useState<BulkFailure[]>([]);
  /** Past-tense verb of the action the current failures came from. */
  const [failureVerb, setFailureVerb] = useState<string>('accepted');
  const [showFailures, setShowFailures] = useState(false);
  const [bundleMenuOpen, setBundleMenuOpen] = useState(false);
  /**
   * Outcome of the last "Recompute proposals" trigger (FRG-SRC-013): the action
   * enqueues background work, so there is nothing to watch on-screen — an
   * inline note is the whole feedback, and a refusal (no ComicVine key) lands
   * in the same place rather than in a toast the operator can miss.
   */
  const [recomputeNote, setRecomputeNote] = useState<{
    text: string;
    error: boolean;
  } | null>(null);

  const queryClient = useQueryClient();
  const syncNow = useSyncSource();
  const recompute = useRecomputeProposals();
  const updateSource = useUpdateSource();
  const disconnect = useDisconnectSource();
  const bulk = useBulkEntitlements();

  // One shared watcher for the manual "Sync now": spins the icon while live and
  // re-derives the whole inventory when the sync command finishes.
  const syncWatch = useWatchedCommand((status) => {
    if (status === 'completed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.sources.all() });
    }
  });
  const syncing = syncNow.isPending || syncWatch.running;

  const all = entitlementsQuery.data ?? NO_ENTITLEMENTS;
  /**
   * One count per filter segment, each the LENGTH of the list that segment
   * shows — derived from `rowsInScope` itself rather than re-tallied, so a
   * segment's count and its select-all can never come apart. (They did: a
   * hand-written tally is a second scoping rule, and the one that governs what
   * select-all takes is `rowsInScope`.)
   */
  const counts = useMemo(
    () =>
      Object.fromEntries(
        FILTERS.map((f) => [f, rowsInScope(all, f).length]),
      ) as Record<Filter, number>,
    [all],
  );
  /**
   * The rows the ACTIVE FILTER shows — the single list the counts, the
   * select-all and every bulk action agree on. Memoized because it feeds the
   * grouping and bundle memos below: a fresh array identity on every render
   * misses those caches, so every unrelated state change would re-fold the
   * entire inventory.
   */
  const visible = useMemo(() => rowsInScope(all, filter), [all, filter]);

  /**
   * The rows an action would ACT ON: the master selection intersected with the
   * active scope, derived at render rather than enforced by editing `selected`.
   *
   * Everything the operator sees is this list — "N selected" counts it, every
   * bulk request carries exactly its ids — so the invariant that an action can
   * only touch rows the current scope shows is unchanged. What changes is that
   * the selection SURVIVES a scope change instead of being trimmed by it: the
   * filter segments are a radiogroup, so ArrowLeft/ArrowRight walk the scopes,
   * and a destructive narrowing meant arrowing one segment past the one you
   * wanted silently destroyed a select-all of 289. Scope changes are now
   * reversible.
   */
  const inScope = useMemo(
    () => visible.filter((e) => selected.has(e.id)),
    [visible, selected],
  );

  /**
   * How many of the current selection each action can actually apply to, by the
   * same per-row preconditions the server enforces (`BULK_APPLIES`).
   *
   * This is the answer to the owner's report that "select all 73 → Restore"
   * only restored some of them: a scope holds one classification but any mix of
   * review statuses, so the truthful number was only discoverable by clicking.
   * Stated on the button, it is discoverable before.
   */
  const applicable = useMemo(() => {
    const tally: Record<BulkAction, number> = {
      accept: 0,
      ignore: 0,
      restore: 0,
      mark_non_comic: 0,
      mark_comic: 0,
    };
    for (const row of inScope) {
      for (const action of Object.keys(tally) as BulkAction[]) {
        if (BULK_APPLIES[action](row)) tally[action] += 1;
      }
    }
    return tally;
  }, [inScope]);

  // Same-title collapse (FRG-UI-029): rows fold into groups by the SERVER's
  // group_key and the list becomes ONE flat array of headers and rows. Every
  // index below — the virtual window, the selection anchor, the shift-range —
  // addresses this array, which is what keeps them coherent with each other.
  const { items, groups } = useMemo(
    () => buildReviewItems(visible, expandedGroups),
    [visible, expandedGroups],
  );
  const bundles = useMemo(() => bundlesInView(visible), [visible]);

  // Virtualized review list (FRG-UI-029): the dogfood corpus is 1,318 rows, so
  // the list renders only the window around the scroll offset plus overscan.
  // Items are dynamically measured because a row can expand (reconcile detail,
  // the FRG-UI-039 search panel) — its height is not a constant.
  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (index) =>
      items[index]?.kind === 'group-header'
        ? GROUP_HEADER_ESTIMATE_PX
        : ROW_ESTIMATE_PX,
    // Keyed by the item's identity, not position: filtering, collapsing or
    // refetching reorders the window without recycling one item's measured
    // height onto another.
    getItemKey: (index) => items[index].key,
    overscan: 8,
    measureElement: (el) => el.getBoundingClientRect().height || ROW_ESTIMATE_PX,
    observeElementRect: (instance, cb) =>
      observeElementRect(instance, (rect) =>
        cb({
          width: rect.width,
          height:
            rect.height || (LAYOUTLESS_ENV ? VIEWPORT_FALLBACK_PX : rect.height),
        }),
      ),
  });
  const virtualRows = virtualizer.getVirtualItems();

  const clearSelection = () => {
    setSelected(new Set());
    setAnchorKey(null);
  };

  /**
   * Select every row the ACTIVE FILTER shows (FRG-UI-029) — the whole filtered
   * list, not the virtual window and not only the groups currently expanded:
   * the screen holds the source's inventory client-side, so "all 289" is
   * exactly that, with no round trip and nothing left behind a scroll position
   * or a fold.
   *
   * It ADDS to the master selection rather than replacing it, so selecting all
   * of one scope does not silently discard a selection made in another. That is
   * safe precisely because `inScope` is what every action reads: a selection
   * held outside the active scope can never be acted on from it.
   */
  const selectAll = () => {
    setSelected((prev) => new Set([...prev, ...visible.map((e) => e.id)]));
    setAnchorKey(null);
  };

  /**
   * Changing scope changes the SCOPE, and nothing else (FRG-UI-029).
   *
   * The selection is held whole and read through the active scope (`inScope`),
   * so moving between segments is non-destructive and reversible — which it has
   * to be, because the segments are a radiogroup and ArrowLeft/ArrowRight move
   * between them: under the old narrowing, arrowing one segment too far shredded
   * a select-all with no way back. The anchor is deliberately left where it was:
   * if it falls outside the new scope, the next shift-click re-anchors on the
   * row it lands on (a range gesture must never deselect).
   */
  const changeFilter = (next: Filter) => setFilter(next);

  // Anchor-based selection (FRG-UI-025) over the flat item array: a plain click
  // toggles one item and becomes the anchor; a shift-click selects the span to
  // the anchor. A group header stands for ALL its rows in both directions — so
  // its checkbox selects the group, and a range that crosses a COLLAPSED group
  // still takes the rows hidden inside it (collapse is presentation, never a
  // selection filter).
  const selectRow = (index: number, shiftKey: boolean) => {
    const item = items[index];
    if (!item) return;
    const ids = itemIds(item);
    const next = new Set(selected);
    if (shiftKey && anchorKey !== null) {
      const anchorIndex = items.findIndex((i) => i.key === anchorKey);
      if (anchorIndex !== -1) {
        const [lo, hi] =
          anchorIndex <= index ? [anchorIndex, index] : [index, anchorIndex];
        for (let k = lo; k <= hi; k += 1) {
          for (const id of itemIds(items[k])) next.add(id);
        }
        setSelected(next);
        return;
      }
      // The anchor is no longer in the list at all (its rows were filtered
      // away, or a refetch dropped them): there is no span to draw. A
      // shift-click then RE-ANCHORS on the clicked item and selects it —
      // degrading to a plain toggle here would silently DESELECT a row the
      // operator was reaching towards, which is the one outcome a range
      // gesture must never produce.
      for (const id of ids) next.add(id);
      setSelected(next);
      setAnchorKey(item.key);
      return;
    }
    // A group toggles as a unit: fully selected -> clear it, otherwise fill it.
    const allSelected = ids.every((id) => next.has(id));
    for (const id of ids) {
      if (allSelected) next.delete(id);
      else next.add(id);
    }
    setSelected(next);
    setAnchorKey(item.key);
  };

  const toggleGroup = (key: string) => {
    const next = new Set(expandedGroups);
    if (next.has(key)) {
      next.delete(key);
      // Collapsing folds this group's rows out of the item array. An anchor
      // sitting on one of them would dangle (findIndex -> -1) and quietly
      // demote the NEXT shift-click, so it moves to the group's header — the
      // header is the group's stand-in in the shared index space (itemIds
      // already treats it as all of its rows), which is exactly where the
      // folded-away anchor now lives.
      if (anchorKey !== null && anchorKey.startsWith('r:')) {
        const anchorId = Number(anchorKey.slice(2));
        const group = groups.find((g) => g.key === key);
        if (group?.rows.some((r) => r.id === anchorId)) {
          setAnchorKey(`g:${key}`);
        }
      }
    } else next.add(key);
    setExpandedGroups(next);
  };

  // "Select bundle" (FRG-SRC-011): the id-list bulk bodies stay id-lists —
  // per-bundle targeting is a SELECTION concern, exactly like shift-range.
  const selectBundle = (name: string) => {
    const next = new Set(selected);
    for (const e of visible) {
      if (e.bundle_human_name === name) next.add(e.id);
    }
    setSelected(next);
    setAnchorKey(null);
    setBundleMenuOpen(false);
  };

  const toggleExpand = (id: number) => {
    const next = new Set(expanded);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setExpanded(next);
  };

  const setRowSearch = (id: number, open: boolean) => {
    setSearchOpen((prev) => {
      const next = new Set(prev);
      if (open) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const setGroupSearch = (key: string, open: boolean) => {
    setGroupSearchOpen((prev) => {
      const next = new Set(prev);
      if (open) next.add(key);
      else next.delete(key);
      return next;
    });
  };

  /** Exactly the ids a bulk request carries: the selection, scoped. */
  const selectedIds = inScope.map((e) => e.id);
  const bulkBusy = bulk.isPending;
  /** The bulk-bar action currently in flight, so its own button can say so. */
  const busyAction: BulkAction | null =
    bulkBusy && bulk.variables && bulk.variables.action !== 'apply_to_group'
      ? bulk.variables.action
      : null;

  /**
   * A bulk button's label: the plain verb when the action applies to the whole
   * selection, and the applicable count when it does not.
   *
   * Stating "30 of 73" only when the two differ keeps the ordinary case quiet;
   * the number appears exactly when it is news.
   */
  const bulkLabel = (action: BulkAction, verb: string) =>
    busyAction === action
      ? BULK_VERBS[action].pending
      : applicable[action] === selectedIds.length
        ? verb
        : `${verb} (${applicable[action]} of ${selectedIds.length})`;

  const resetBulkFeedback = () => {
    setBulkNote(null);
    setFailures([]);
    setShowFailures(false);
  };

  /**
   * Bulk action over the selection (FRG-SRC-011): ONE request in which the
   * server applies EACH row in its own transaction — for `accept`, each row's
   * own stored proposal, which is the apply-to-a-whole-group/bundle move.
   * Replaces the old client-side loop, which needed one round trip per row and
   * could half-finish invisibly.
   *
   * EVERY action reports the same way, because every action can half-succeed: a
   * row that cannot be applied (no proposal, already gone) comes back in the
   * per-row `errors` map while the rest still apply. Reporting only accept's
   * failures would let a partial ignore/restore read as complete — the selection
   * clearing away the rows that did NOT move. So the failures are always named,
   * and only they stay selected.
   *
   * The report is written against a SETTLED list: the hook awaits its own
   * invalidation (bounded — see `useSettledInvalidateSources`), so this callback
   * runs only once the entitlements have refetched and "Restored 12 of 30"
   * cannot render beside a list still showing all thirty parked.
   */
  const applyBulk = (action: BulkAction) => {
    if (selectedIds.length === 0 || bulkBusy) return;
    const attempted = selectedIds.length;
    const attemptedIds = selectedIds;
    resetBulkFeedback();
    bulk.mutate(
      { action, entitlementIds: attemptedIds },
      {
        onSuccess: (result) => {
          const entries = Object.entries(result.errors ?? {});
          setBulkNote(
            `${BULK_VERBS[action].note} ${result.applied} of ${attempted}.`,
          );
          // Only the ATTEMPTED ids are released, never the whole master set: a
          // selection standing in another scope was not part of this action and
          // must survive it, exactly as it survives a scope change.
          const release = (keep: readonly number[]) =>
            setSelected((prev) => {
              const next = new Set(prev);
              for (const id of attemptedIds) next.delete(id);
              for (const id of keep) next.add(id);
              return next;
            });
          if (entries.length === 0) {
            release([]);
            setAnchorKey(null);
            return;
          }
          const failed = entries.map(([id, message]) => {
            const numericId = Number(id);
            return {
              id: numericId,
              name:
                all.find((e) => e.id === numericId)?.human_name ??
                `Item ${id}`,
              message,
            };
          });
          // Keep ONLY the failures selected: the succeeded rows have moved on
          // (and refetch out of `new`), the failures are what still needs a
          // decision, so the selection becomes the to-do list.
          release(failed.map((f) => f.id));
          setAnchorKey(null);
          setFailures(failed);
          setFailureVerb(BULK_VERBS[action].past);
        },
        onError: (err) => setBulkNote(err.message),
      },
    );
  };

  /**
   * Resolve a WHOLE same-title group to one picked candidate (FRG-UI-043): the
   * group-header search's `onPick`. A candidate already in the library
   * (`have_it`) is resolved to its local series id and every member is matched
   * to it; one not yet in the library carries only its cv_volume_id, and the
   * server adds it ONCE and leaves the rest as swept proposals for a single
   * bulk accept. A `have_it` candidate the fetched index cannot name (added
   * since the index loaded) falls through to the cv_volume_id path, where the
   * backend degrades the add to a match (FRG-SRC-008) — so no member is lost.
   * The bulk hook's own success invalidation re-derives the list, so the fresh
   * matches and swept proposals render without a hand-rolled refetch.
   */
  const applyGroupMatch = (group: ReviewGroup, candidate: PickedCandidate) => {
    if (bulkBusy) return;
    const ids = group.rows.map((r) => r.id);
    const owned = candidate.have_it
      ? librarySeries.find((s) => s.cv_volume_id === candidate.cv_volume_id)
      : undefined;
    const input = owned
      ? {
          action: 'apply_to_group' as const,
          entitlementIds: ids,
          seriesId: owned.id,
        }
      : {
          action: 'apply_to_group' as const,
          entitlementIds: ids,
          cvVolumeId: candidate.cv_volume_id,
        };
    resetBulkFeedback();
    bulk.mutate(input, {
      onSuccess: () => {
        setGroupSearch(group.key, false);
        setBulkNote(
          owned
            ? `Matched all ${ids.length} items in ${group.title}.`
            : `Added ${candidate.name ?? group.title}; the rest are proposed for one bulk accept.`,
        );
      },
      onError: (err) => setBulkNote(err.message),
    });
  };

  return (
    <div data-testid="store-manage">
      {/* Account bar */}
      <div className={styles.accountBar}>
        <span className={styles.cardTile} aria-hidden>
          <i className="fa-solid fa-bag-shopping" />
        </span>
        <div className={styles.accountMain}>
          <span className={styles.accountName}>{source.name}</span>
          <span className={styles.accountStatus}>
            <span className={`${styles.statusDot} ${styles.dotConnected}`} aria-hidden />
            Connected
            {source.last_sync_status ? ` · last sync ${source.last_sync_status}` : ''}
          </span>
        </div>
        <div className={styles.accountActions}>
          {/* Quiet by default (FRG-UI-040): this appears only once a ComicVine
              path bucket is at/above its warning fraction. The review queue is
              where an operator spends the budget without thinking about it —
              accepting rows, searching, restoring — so this is where the
              "about to run out" fact has to land, and nowhere else. */}
          <ComicVineBudgetChip />
          <span className={styles.autoLabel}>
            Auto-sync new purchases
            <Toggle
              checked={source.auto_sync}
              onChange={(next) =>
                updateSource.mutate({ sourceId: source.id, auto_sync: next })
              }
              disabled={updateSource.isPending}
              label="Auto-sync new purchases"
              title="Auto-match and add confidently matched new purchases on each sync"
              testId="auto-sync-manage"
            />
          </span>
          <span className={styles.divider} aria-hidden />
          <button
            type="button"
            className={styles.textBtn}
            disabled={syncing}
            data-testid="sync-now"
            onClick={() =>
              syncNow.mutate(source.id, {
                onSuccess: (res) => syncWatch.start(res.command_id),
              })
            }
          >
            <i
              className={`fa-solid fa-arrows-rotate ${syncing ? styles.spin : ''}`}
              aria-hidden
            />{' '}
            {syncing ? 'Syncing…' : 'Sync now'}
          </button>
          {/* Bulk proposal refresh (FRG-SRC-013): proposals stored before the
              ComicVine-first universe (or while no key was configured) are
              non-NULL and so can never re-enter the nightly enrichment pass —
              this is the operator's way to ask for them again. The default
              request leaves markers alone (`include_markers` stays API-only):
              re-asking about every "we looked, there is nothing" row is real
              budget spend, and no affordance for it fits this bar without
              putting a second decision in front of the primary action. */}
          <button
            type="button"
            className={styles.textBtn}
            disabled={recompute.isPending}
            data-testid="recompute-proposals"
            title="Re-run matching for items still awaiting review, in budget-polite batches"
            onClick={() => {
              setRecomputeNote(null);
              recompute.mutate(
                { sourceId: source.id },
                {
                  onSuccess: () =>
                    setRecomputeNote({
                      text: 'Recompute queued — running in the background.',
                      error: false,
                    }),
                  onError: (err) =>
                    setRecomputeNote({ text: err.message, error: true }),
                },
              );
            }}
          >
            <i className="fa-solid fa-wand-magic-sparkles" aria-hidden />{' '}
            {recompute.isPending ? 'Queueing…' : 'Recompute proposals'}
          </button>
          <button
            type="button"
            className={styles.dangerBtn}
            data-testid="disconnect"
            onClick={() => disconnect.mutate(source.id)}
          >
            Disconnect
          </button>
        </div>
      </div>

      {/* Recompute outcome (FRG-SRC-013) — queued as an info line, a refusal in
          the screen's error-note idiom, both carrying the server's own words. */}
      {recomputeNote &&
        (recomputeNote.error ? (
          <p
            className={styles.connectError}
            role="alert"
            data-testid="recompute-note"
          >
            {recomputeNote.text}
          </p>
        ) : (
          <div
            className={styles.infoLine}
            role="status"
            data-testid="recompute-note"
          >
            <i
              className={`fa-solid fa-circle-info ${styles.infoIcon}`}
              aria-hidden
            />
            <span>{recomputeNote.text}</span>
          </div>
        ))}

      {source.auto_sync && (
        <div className={styles.infoLine}>
          <i className={`fa-solid fa-circle-info ${styles.infoIcon}`} aria-hidden />
          <span>
            New Humble purchases are matched and added automatically; matched
            collected editions mark their issues as owned. You review anything
            ambiguous below.
          </span>
        </div>
      )}

      {/* Count line + filters */}
      <div className={styles.countRow}>
        <span className={styles.countLine} data-testid="count-line">
          {counts.all} items · <span className={styles.countMatched}>{counts.matched} matched</span> ·{' '}
          <span className={styles.countNew}>{counts.new} new</span> · {counts.ignored} ignored
        </span>
        <div className={styles.filters}>
          {/* Non-comic sits in the same control as the review statuses
              (FRG-UI-029 / FRG-SRC-016): it is a scope the operator moves INTO,
              with its own count, not a switch that mixes another kind of row
              into the scope they are already in. */}
          <SegmentedControl<Filter>
            ariaLabel="Filter entitlements by review status"
            value={filter}
            onChange={changeFilter}
            options={[
              { value: 'all', label: `All ${counts.all}`, testId: 'filter-all' },
              { value: 'new', label: `New ${counts.new}`, testId: 'filter-new' },
              { value: 'matched', label: `Matched ${counts.matched}`, testId: 'filter-matched' },
              { value: 'ignored', label: `Ignored ${counts.ignored}`, testId: 'filter-ignored' },
              { value: 'duplicate', label: `Duplicates ${counts.duplicate}`, testId: 'filter-duplicate' },
              { value: 'other', label: `Non-comic ${counts.other}`, testId: 'filter-other' },
            ]}
          />
        </div>
      </div>

      {/* Bulk bar — always available for a non-empty list, because the bundle
          selector is how a selection STARTS at corpus scale. */}
      {(visible.length > 0 || selectedIds.length > 0) && (
        <div className={styles.bulkBar} data-testid="bulk-bar">
          <span>{selectedIds.length} selected</span>
          {/* Names its own count, because the count IS the reassurance: the
              filtered list is longer than the window, so "Select all 289" is
              the only way the operator knows what the next action will touch. */}
          <button
            type="button"
            className={styles.linkBtn}
            disabled={visible.length === 0 || bulkBusy}
            onClick={selectAll}
            data-testid="select-all"
            title="Select every item this filter shows"
          >
            Select all {visible.length}
          </button>
          <Menu
            open={bundleMenuOpen}
            onOpenChange={setBundleMenuOpen}
            label="Select bundle…"
            icon={<i className="fa-solid fa-box-open" aria-hidden />}
            align="start"
            disabled={bundles.length === 0}
            triggerTitle={
              bundles.length === 0
                ? 'No bundle names on these items yet — they arrive with the next sync'
                : 'Select every visible item from one bundle'
            }
            testId="select-bundle"
            menuTestId="select-bundle-menu"
          >
            {bundles.map((bundle) => (
              <button
                key={bundle.name}
                type="button"
                role="menuitem"
                className={styles.bundleOption}
                data-menuitem
                data-testid={`bundle-option-${bundle.name}`}
                onClick={() => selectBundle(bundle.name)}
              >
                <span className={styles.bundleOptionName}>{bundle.name}</span>
                <span className={styles.bundleOptionCount}>{bundle.count}</span>
              </button>
            ))}
          </Menu>
          {selectedIds.length > 0 && (
            <>
              {/* Each action states how much of the SELECTION it can apply to
                  whenever that is not all of it, and refuses to be clicked when
                  it is none of it (FRG-UI-029). A scope holds one
                  classification but any mix of review statuses, so "select all
                  73 → Restore" legitimately reaches rows restore refuses — the
                  count is what makes that visible before the click rather than
                  as a panel of refusals after it. */}
              <button
                type="button"
                className={styles.linkBtn}
                disabled={bulkBusy || applicable.accept === 0}
                onClick={() => applyBulk('accept')}
                data-testid="bulk-accept"
              >
                {bulkLabel('accept', 'Accept matches')}
              </button>
              <button
                type="button"
                className={styles.linkBtn}
                disabled={bulkBusy || applicable.ignore === 0}
                onClick={() => applyBulk('ignore')}
                data-testid="bulk-ignore"
              >
                {bulkLabel('ignore', 'Ignore')}
              </button>
              <button
                type="button"
                className={styles.mutedBtn}
                disabled={bulkBusy || applicable.restore === 0}
                onClick={() => applyBulk('restore')}
                data-testid="bulk-restore"
              >
                {bulkLabel('restore', 'Restore')}
              </button>
              {/* The mark the 73-item non-comic bundle needs (FRG-SRC-016):
                  select the bundle, mark it, and no later sync moves it back.
                  Each scope offers the ONE direction that can be true of what
                  is on screen — the reverse mark lives in the non-comic scope,
                  where its rows are. */}
              {filter === 'other' ? (
                <button
                  type="button"
                  className={styles.mutedBtn}
                  disabled={bulkBusy || applicable.mark_comic === 0}
                  onClick={() => applyBulk('mark_comic')}
                  data-testid="bulk-mark-comic"
                >
                  {bulkLabel('mark_comic', 'It is a comic')}
                </button>
              ) : (
                <button
                  type="button"
                  className={styles.mutedBtn}
                  disabled={bulkBusy || applicable.mark_non_comic === 0}
                  onClick={() => applyBulk('mark_non_comic')}
                  data-testid="bulk-mark-non-comic"
                >
                  {bulkLabel('mark_non_comic', 'Not a comic')}
                </button>
              )}
              <button
                type="button"
                className={styles.mutedBtn}
                onClick={clearSelection}
              >
                Clear
              </button>
            </>
          )}
          {bulkNote && (
            <span className={styles.bulkNote} role="alert">
              {bulkNote}
            </span>
          )}
        </div>
      )}

      {/* Per-row bulk failures (FRG-SRC-011): a count, expandable to the rows
          the action could not be applied to and why — no bulk action is ever
          silently partial. */}
      {failures.length > 0 && (
        <div className={styles.bulkErrors} data-testid="bulk-errors">
          <button
            type="button"
            className={styles.linkBtn}
            aria-expanded={showFailures}
            onClick={() => setShowFailures(!showFailures)}
            data-testid="bulk-errors-toggle"
          >
            {failures.length} item{failures.length === 1 ? '' : 's'} could not be{' '}
            {failureVerb}
          </button>
          {showFailures && (
            <ul className={styles.bulkErrorList} data-testid="bulk-errors-detail">
              {failures.map((failure) => (
                <li key={failure.id} data-testid={`bulk-error-${failure.id}`}>
                  <span className={styles.bulkErrorName}>{failure.name}</span> —{' '}
                  {failure.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* List */}
      {entitlementsQuery.isLoading && (
        <p className={styles.stateNote}>Loading entitlements…</p>
      )}
      {!entitlementsQuery.isLoading && visible.length === 0 && (
        <p className={styles.stateNote} data-testid="empty-list">
          Nothing to review here yet — Humble purchases appear after a sync.
        </p>
      )}
      {visible.length > 0 && (
        <div className={styles.list}>
          <div
            ref={scrollRef}
            className={styles.listScroll}
            data-testid="entitlement-scroller"
          >
            <div
              style={{ height: virtualizer.getTotalSize(), position: 'relative' }}
              data-testid="entitlement-list"
              data-total-rows={visible.length}
              data-total-items={items.length}
            >
              {virtualRows.map((virtualRow) => {
                const item = items[virtualRow.index];
                if (!item) return null;
                return (
                  <div
                    key={virtualRow.key}
                    className={
                      item.kind === 'row' && item.group
                        ? `${styles.virtualRow} ${styles.groupedRow}`
                        : styles.virtualRow
                    }
                    // measureElement reads data-index off the element itself.
                    data-index={virtualRow.index}
                    ref={virtualizer.measureElement}
                    style={{ transform: `translateY(${virtualRow.start}px)` }}
                  >
                    {item.kind === 'group-header' ? (
                      <EntitlementGroupHeader
                        group={item.group}
                        index={virtualRow.index}
                        collapsed={item.collapsed}
                        selected={item.group.rows.every((r) =>
                          selected.has(r.id),
                        )}
                        partiallySelected={item.group.rows.some((r) =>
                          selected.has(r.id),
                        )}
                        searchOpen={groupSearchOpen.has(item.group.key)}
                        searchBusy={bulkBusy}
                        onSelectRow={selectRow}
                        onToggleCollapse={() => toggleGroup(item.group.key)}
                        onSetSearchOpen={(open) =>
                          setGroupSearch(item.group.key, open)
                        }
                        onPick={(candidate) =>
                          applyGroupMatch(item.group, candidate)
                        }
                      />
                    ) : (
                      <EntitlementRow
                        entitlement={item.entitlement}
                        index={virtualRow.index}
                        selected={selected.has(item.entitlement.id)}
                        onSelectRow={selectRow}
                        expanded={expanded.has(item.entitlement.id)}
                        onToggleExpand={() => toggleExpand(item.entitlement.id)}
                        searchOpen={searchOpen.has(item.entitlement.id)}
                        onSetSearchOpen={(open) =>
                          setRowSearch(item.entitlement.id, open)
                        }
                        librarySeries={librarySeries}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
