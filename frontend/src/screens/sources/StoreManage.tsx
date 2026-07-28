import { useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { observeElementRect, useVirtualizer } from '@tanstack/react-virtual';
import { SegmentedControl } from '../../components/SegmentedControl';
import { Toggle } from '../../components/Toggle';
import { EntitlementRow } from './EntitlementRow';
import { useSeriesIndex, useWatchedCommand } from '../../api/hooks';
import {
  useBulkEntitlements,
  useDisconnectSource,
  useEntitlements,
  useMatchEntitlement,
  useSyncSource,
  useUpdateSource,
} from '../../api/sourceHooks';
import { queryKeys } from '../../api/queryKeys';
import type { EntitlementResource, StoreSourceResource } from '../../api/types';
import styles from './sources.module.css';

type Filter = 'all' | 'new' | 'matched' | 'ignored';

/**
 * Starting height guess for one collapsed review row (FRG-UI-029). Every
 * mounted row is measured for real (`measureElement`), so this only shapes the
 * scrollbar before a row has been seen — and doubles as the fallback when the
 * environment reports no layout at all (jsdom), keeping the windowing math
 * coherent under test.
 */
const ROW_ESTIMATE_PX = 78;

/**
 * Viewport height assumed when the scroll container reports none. A
 * zero-height measurement means "this environment did no layout" (jsdom) — the
 * virtualizer's own answer to a zero viewport is to render NOTHING, which
 * would turn a layout-less environment into a silently empty list. Falling
 * back to a nominal viewport keeps the list windowing coherently instead.
 */
const VIEWPORT_FALLBACK_PX = 720;

/**
 * Connected-store manage view (FRG-UI-029): account bar (auto-sync toggle, Sync
 * now, Disconnect), the count line + All/New/Matched/Ignored filter segments and
 * a non-comic reveal, and the reviewable entitlement list — virtualized, so a
 * first sync at corpus scale (1,318 rows in the dogfood account) stays
 * responsive — with bulk select (including shift-range, the FRG-UI-025
 * pattern; selection is id/index based over the filtered list, so it spans
 * rows the window has scrolled past).
 */
export function StoreManage({ source }: { source: StoreSourceResource }) {
  const entitlementsQuery = useEntitlements(source.id);
  const seriesQuery = useSeriesIndex();
  const librarySeries = seriesQuery.data ?? [];

  const [filter, setFilter] = useState<Filter>('all');
  const [showOther, setShowOther] = useState(false);
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set());
  const [anchorId, setAnchorId] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(new Set());
  const [bulkNote, setBulkNote] = useState<string | null>(null);

  const queryClient = useQueryClient();
  const syncNow = useSyncSource();
  const updateSource = useUpdateSource();
  const disconnect = useDisconnectSource();
  const bulk = useBulkEntitlements();
  const match = useMatchEntitlement();
  const [accepting, setAccepting] = useState(false);

  // One shared watcher for the manual "Sync now": spins the icon while live and
  // re-derives the whole inventory when the sync command finishes.
  const syncWatch = useWatchedCommand((status) => {
    if (status === 'completed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.sources.all() });
    }
  });
  const syncing = syncNow.isPending || syncWatch.running;

  const all = entitlementsQuery.data ?? [];
  // The non-comic toggle scopes the whole surface; segment counts + the count
  // line are computed over the same scope so they always agree with the list.
  const scoped = all.filter((e) => showOther || e.classification === 'comic');
  const count = (s: EntitlementResource['review_status']) =>
    scoped.filter((e) => e.review_status === s).length;
  const counts = {
    all: scoped.length,
    new: count('new'),
    matched: count('matched'),
    ignored: count('ignored'),
  };
  const visible =
    filter === 'all' ? scoped : scoped.filter((e) => e.review_status === filter);

  // Virtualized review list (FRG-UI-029): the dogfood corpus is 1,318 rows, so
  // the list renders only the window around the scroll offset plus overscan.
  // Rows are dynamically measured because a row can expand (reconcile detail,
  // the FRG-UI-039 search panel) — its height is not a constant.
  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: visible.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_ESTIMATE_PX,
    // Keyed by entitlement id, not position: filtering/refetching reorders the
    // window without recycling one row's measured height onto another row.
    getItemKey: (index) => visible[index].id,
    overscan: 8,
    measureElement: (el) => el.getBoundingClientRect().height || ROW_ESTIMATE_PX,
    observeElementRect: (instance, cb) =>
      observeElementRect(instance, (rect) =>
        cb({ width: rect.width, height: rect.height || VIEWPORT_FALLBACK_PX }),
      ),
  });
  const virtualRows = virtualizer.getVirtualItems();

  const clearSelection = () => {
    setSelected(new Set());
    setAnchorId(null);
  };

  // Anchor-based selection (FRG-UI-025): a plain click toggles one row and
  // becomes the anchor; a shift-click selects the visible span to the anchor.
  const selectRow = (index: number, shiftKey: boolean) => {
    const id = visible[index].id;
    if (shiftKey && anchorId !== null) {
      const anchorIndex = visible.findIndex((e) => e.id === anchorId);
      if (anchorIndex !== -1) {
        const [lo, hi] =
          anchorIndex <= index ? [anchorIndex, index] : [index, anchorIndex];
        const next = new Set(selected);
        for (let k = lo; k <= hi; k += 1) next.add(visible[k].id);
        setSelected(next);
        return;
      }
    }
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
    setAnchorId(id);
  };

  const toggleExpand = (id: number) => {
    const next = new Set(expanded);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setExpanded(next);
  };

  const selectedIds = [...selected];
  const bulkBusy = bulk.isPending || accepting;

  const runBulk = (action: 'ignore' | 'restore') => {
    if (selectedIds.length === 0 || bulkBusy) return;
    setBulkNote(null);
    bulk.mutate(
      { action, entitlementIds: selectedIds },
      { onSuccess: clearSelection },
    );
  };

  // Bulk "Accept matches" — accept every selected NEW row that has a confident
  // library proposal, sequentially through the review endpoint (the bulk match
  // endpoint takes ONE shared series_id, which cannot be right across rows).
  const acceptSelected = async () => {
    if (bulkBusy) return;
    const targets = scoped.filter(
      (e) =>
        selected.has(e.id) &&
        e.review_status === 'new' &&
        e.proposed_series_id != null,
    );
    if (targets.length === 0) {
      setBulkNote('No selected rows have a library match to accept.');
      return;
    }
    setAccepting(true);
    setBulkNote(null);
    let done = 0;
    try {
      for (const e of targets) {
        await match.mutateAsync({
          entitlementId: e.id,
          seriesId: e.proposed_series_id as number,
        });
        done += 1;
      }
      clearSelection();
    } catch {
      setBulkNote(`Accepted ${done} of ${targets.length}; the rest failed.`);
    } finally {
      setAccepting(false);
    }
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
          <SegmentedControl<Filter>
            ariaLabel="Filter entitlements by review status"
            value={filter}
            onChange={setFilter}
            options={[
              { value: 'all', label: `All ${counts.all}`, testId: 'filter-all' },
              { value: 'new', label: `New ${counts.new}`, testId: 'filter-new' },
              { value: 'matched', label: `Matched ${counts.matched}`, testId: 'filter-matched' },
              { value: 'ignored', label: `Ignored ${counts.ignored}`, testId: 'filter-ignored' },
            ]}
          />
          <label className={styles.otherToggle}>
            <Toggle
              checked={showOther}
              onChange={setShowOther}
              label="Show non-comic items"
              testId="toggle-noncomic"
            />
            Non-comic
          </label>
        </div>
      </div>

      {/* Bulk bar */}
      {selectedIds.length > 0 && (
        <div className={styles.bulkBar} data-testid="bulk-bar">
          <span>{selectedIds.length} selected</span>
          <button
            type="button"
            className={styles.linkBtn}
            disabled={bulkBusy}
            onClick={acceptSelected}
            data-testid="bulk-accept"
          >
            Accept matches
          </button>
          <button
            type="button"
            className={styles.linkBtn}
            disabled={bulkBusy}
            onClick={() => runBulk('ignore')}
            data-testid="bulk-ignore"
          >
            Ignore
          </button>
          <button
            type="button"
            className={styles.mutedBtn}
            disabled={bulkBusy}
            onClick={() => runBulk('restore')}
            data-testid="bulk-restore"
          >
            Restore
          </button>
          <button type="button" className={styles.mutedBtn} onClick={clearSelection}>
            Clear
          </button>
          {bulkNote && (
            <span className={styles.bulkNote} role="alert">
              {bulkNote}
            </span>
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
            >
              {virtualRows.map((virtualRow) => {
                const e = visible[virtualRow.index];
                return (
                  <div
                    key={virtualRow.key}
                    className={styles.virtualRow}
                    // measureElement reads data-index off the element itself.
                    data-index={virtualRow.index}
                    ref={virtualizer.measureElement}
                    style={{ transform: `translateY(${virtualRow.start}px)` }}
                  >
                    <EntitlementRow
                      entitlement={e}
                      index={virtualRow.index}
                      selected={selected.has(e.id)}
                      onSelectRow={selectRow}
                      expanded={expanded.has(e.id)}
                      onToggleExpand={() => toggleExpand(e.id)}
                      librarySeries={librarySeries}
                    />
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
