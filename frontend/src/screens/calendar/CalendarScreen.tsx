import { useMemo, useState, type CSSProperties } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Toolbar } from '../../components/Toolbar';
import { SegmentedControl } from '../../components/SegmentedControl';
import {
  BookmarkIcon,
  CheckIcon,
  PlusIcon,
  RefreshIcon,
  SearchIcon,
  SpinnerIcon,
} from '../../components/icons';
import {
  useRunCommand,
  useToggleIssueMonitored,
  useWatchedCommand,
  useWeeklyPull,
} from '../../api/hooks';
import { queryKeys } from '../../api/queryKeys';
import type {
  AddSeriesNavigationState,
  PullEntryRecord,
} from '../../api/types';
import { publisherAccent, publisherTint } from '../../theme/palettes';
import {
  addWeeks,
  currentIsoWeek,
  isoDateKey,
  weekDates,
  weekRangeLabel,
} from '../../utils/isoWeek';
import styles from './CalendarScreen.module.css';

/**
 * Calendar — weekly pull / release agenda (FRG-UI-018). Renders FRG-API-019's
 * merged projection as a date-grouped agenda (design handoff v2 §4), one ISO
 * week at a time: comics ship in one Wednesday drop, so a 7-column grid would
 * pile everything on New Comic Day.
 *
 * The URL carries `?week=` only (shareable, back/forward works); scope
 * (Following/All) and the publisher filter are client-side view state over the
 * whole loaded week (the hook aggregates every page — design decisions 1 & 4).
 * Per-entry want/skip/search actions (FRG-PULL-007) delegate to the canonical
 * issue operations; the pull endpoint stays read-only (D4). New-series debuts
 * surface in a distinct strip with a prefilled add hand-off (FRG-PULL-008).
 */

type Scope = 'following' | 'all';

const SCOPE_OPTIONS = [
  { value: 'following' as const, label: 'Following' },
  { value: 'all' as const, label: 'All releases' },
];

/** "Following" = linked to a library series (matched) or matched-but-pending. */
function isFollowing(r: PullEntryRecord): boolean {
  return r.series != null || r.state === 'pending_refresh';
}

/** Display name for a row (the linked series title wins over the raw name). */
function rowName(r: PullEntryRecord): string {
  return r.series?.title ?? r.seriesName;
}

/** A row's issue · publisher subtitle. */
function rowSub(r: PullEntryRecord): string {
  const issue = r.issueNumber != null ? `#${r.issueNumber}` : '—';
  return `${issue} · ${r.publisher ?? 'Unknown'}`;
}

/** The card's cover spine style — publisher tint + accent edge (palettes.ts). */
function spineStyle(r: PullEntryRecord): CSSProperties {
  return {
    backgroundColor: publisherTint(r.publisher),
    borderLeft: `2px solid ${publisherAccent(r.publisher)}`,
  };
}

/** The derived-state glyph shown on a card (a projection of `state`, D4). */
function StateGlyph({ state }: { state: PullEntryRecord['state'] }) {
  switch (state) {
    case 'downloaded':
      return (
        <span className={`${styles.stateGlyph} ${styles.toneSuccess}`} title="Downloaded">
          <CheckIcon size={13} />
        </span>
      );
    case 'downloading':
      return (
        <span className={`${styles.stateGlyph} ${styles.toneInfo}`} title="Downloading">
          <SpinnerIcon size={13} />
        </span>
      );
    case 'missing_wanted':
      return (
        <span className={`${styles.stateGlyph} ${styles.toneAccent}`} title="Wanted">
          <BookmarkIcon size={13} filled />
        </span>
      );
    case 'pending_refresh':
      return (
        <span className={`${styles.stateGlyph} ${styles.toneWait}`} title="Pending refresh">
          <RefreshIcon size={13} />
        </span>
      );
    default:
      // unmonitored / unmatched (null) — a quiet outline bookmark.
      return (
        <span className={`${styles.stateGlyph} ${styles.toneMuted}`} title="Not tracked">
          <BookmarkIcon size={13} />
        </span>
      );
  }
}

export function CalendarScreen() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const thisWeek = currentIsoWeek();
  const week = searchParams.get('week') ?? thisWeek;

  const [scope, setScope] = useState<Scope>('following');
  const [publisher, setPublisher] = useState<string>('all');

  const { data, isLoading, isError } = useWeeklyPull(week);
  const records = useMemo(() => data ?? [], [data]);

  // Per-entry search reuses the Wanted screen's single-watcher seam: a completed
  // search may have grabbed a release, so re-project the pull view + wanted list
  // + queue on terminal success (design decision 5).
  const runCommand = useRunCommand();
  const toggle = useToggleIssueMonitored();
  const [commandLabel, setCommandLabel] = useState<string | null>(null);
  const command = useWatchedCommand((status) => {
    if (status === 'completed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.pull.all() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.wanted.all() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.queue.all() });
    }
  });

  const todayKey = useMemo(() => {
    const now = new Date();
    return isoDateKey(
      new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())),
    );
  }, []);

  const view = useMemo(() => {
    // Publisher options span every publisher present in the loaded week.
    const publishers = Array.from(
      new Set(records.map((r) => r.publisher).filter((p): p is string => !!p)),
    ).sort();

    const pubFiltered =
      publisher === 'all'
        ? records
        : records.filter((r) => r.publisher === publisher);

    // New-series debuts render in their own strip and are excluded from the
    // agenda so a row is never double-counted (design decision 6).
    const newSeries = pubFiltered.filter((r) => r.matchType === 'new_series');
    const agenda = pubFiltered.filter((r) => r.matchType !== 'new_series');

    const weekAll = agenda.length;
    const weekFollowed = agenda.filter(isFollowing).length;
    const visible =
      scope === 'following' ? agenda.filter(isFollowing) : agenda;

    const days = weekDates(week)
      .map((date) => {
        const key = isoDateKey(date);
        const dayVisible = visible.filter((r) => r.releaseDate === key);
        const dayAll = agenda.filter((r) => r.releaseDate === key);
        const followed = dayVisible.filter(isFollowing).length;
        const hidden = dayAll.length - dayVisible.length;
        const dow = date.getUTCDay(); // 0=Sun … 3=Wed … 6=Sat
        return {
          key,
          date: date.getUTCDate(),
          dow: date.toLocaleDateString('en-US', { weekday: 'short', timeZone: 'UTC' }),
          mon: date.toLocaleDateString('en-US', { month: 'short', timeZone: 'UTC' }),
          isNewComicDay: dow === 3,
          isToday: key === todayKey,
          isFuture: key > todayKey,
          releases: dayVisible,
          count: dayVisible.length,
          followed,
          hidden,
        };
      })
      .filter((d) => d.count > 0);

    return { publishers, newSeries, weekAll, weekFollowed, days };
  }, [records, publisher, scope, week, todayKey]);

  const banner =
    scope === 'following'
      ? `Comics ship in one big weekly drop. You're seeing the ${view.weekFollowed} ` +
        `issue${view.weekFollowed === 1 ? '' : 's'} from series you follow — ` +
        `${view.weekAll - view.weekFollowed} more titles ship this week across every publisher.`
      : `Showing all ${view.weekAll} single issues shipping this week — ` +
        `${view.weekFollowed} from series you already follow.`;

  const dispatchSearch = (r: PullEntryRecord) => {
    runCommand.mutate(
      {
        name: 'issue-search',
        payload: { series_id: r.series?.id, issue_id: r.matchedIssueId },
      },
      {
        onSuccess: (rec) => {
          setCommandLabel(`Search ${rowName(r)}`);
          command.start(rec.id);
        },
      },
    );
  };

  const addNewSeries = (r: PullEntryRecord) => {
    const state: AddSeriesNavigationState = { prefillTerm: r.seriesName };
    navigate('/add', { state });
  };

  /** One release card. Linked rows (matchedIssueId set) expose want/skip +
   * search; unlinked rows expose only their derived-state glyph (FRG-PULL-007). */
  const renderCard = (r: PullEntryRecord, isFuture: boolean) => {
    const linked = r.matchedIssueId != null;
    const monitored = r.state !== 'unmonitored';
    const name = rowName(r);
    const cardKey = r.id ?? `${r.seriesName}-${r.issueNumber}-${r.matchedIssueId}`;
    const cls = [
      styles.card,
      linked ? '' : styles.cardUnlinked,
      isFuture ? styles.cardFuture : '',
    ]
      .filter(Boolean)
      .join(' ');
    return (
      <div
        key={cardKey}
        className={cls}
        data-testid={`calendar-card-${cardKey}`}
        data-linked={linked}
        data-future={isFuture}
      >
        <div className={styles.spine} style={spineStyle(r)} aria-hidden />
        <div className={styles.cardBody}>
          <div className={styles.cardTitle}>{name}</div>
          <div className={styles.cardSub}>{rowSub(r)}</div>
          {isFuture && <div className={styles.unreleased}>Not yet released</div>}
        </div>
        {linked ? (
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.iconBtn}
              aria-label={`${monitored ? 'Skip' : 'Want'} ${name}`}
              title={monitored ? 'Stop monitoring' : 'Monitor / want'}
              onClick={() =>
                toggle.mutate({ issueId: r.matchedIssueId as number, monitored: !monitored })
              }
            >
              <BookmarkIcon size={13} filled={monitored} />
            </button>
            <button
              type="button"
              className={styles.iconBtn}
              aria-label={`Search for ${name}`}
              title="Automatic search"
              disabled={command.running}
              onClick={() => dispatchSearch(r)}
            >
              <SearchIcon size={13} />
            </button>
          </div>
        ) : (
          <StateGlyph state={r.state} />
        )}
      </div>
    );
  };

  return (
    <>
      <Toolbar
        title="Calendar"
        actions={
          <span className={styles.toolbarActions}>
            {commandLabel && command.status && (
              <span className={styles.commandChip} data-testid="command-status">
                {commandLabel}: {command.status}
              </span>
            )}
            <select
              className={styles.pubSelect}
              aria-label="Filter by publisher"
              value={publisher}
              onChange={(e) => setPublisher(e.target.value)}
            >
              <option value="all">All publishers</option>
              {view.publishers.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
            <SegmentedControl
              options={SCOPE_OPTIONS}
              value={scope}
              onChange={setScope}
              ariaLabel="Release scope"
            />
          </span>
        }
      />
      <div className={styles.screen}>
        <div className={styles.weekBar}>
          <div className={styles.weekNav}>
            <button
              type="button"
              className={styles.navBtn}
              aria-label="Previous week"
              onClick={() => setSearchParams({ week: addWeeks(week, -1) })}
            >
              <i className="fa-solid fa-chevron-left" aria-hidden />
            </button>
            <button
              type="button"
              className={styles.thisWeek}
              onClick={() => setSearchParams({})}
            >
              This Week
            </button>
            <button
              type="button"
              className={styles.navBtn}
              aria-label="Next week"
              onClick={() => setSearchParams({ week: addWeeks(week, 1) })}
            >
              <i className="fa-solid fa-chevron-right" aria-hidden />
            </button>
          </div>
          <span className={styles.rangeLabel} data-testid="week-range">
            {weekRangeLabel(week)}
          </span>
        </div>

        {isLoading && <p className={styles.stateMsg}>Loading this week&rsquo;s releases…</p>}
        {isError && (
          <p className={styles.stateMsg}>Could not load the weekly release list.</p>
        )}

        {!isLoading && !isError && (
          <>
            <div className={styles.banner}>
              <i className={`fa-solid fa-layer-group ${styles.bannerIcon}`} aria-hidden />
              <div className={styles.bannerText}>{banner}</div>
            </div>

            {view.newSeries.length > 0 && (
              <section className={styles.strip} data-testid="new-this-week">
                <div className={styles.stripHeading}>New this week</div>
                <div className={styles.stripItems}>
                  {view.newSeries.map((r) => {
                    const cardKey =
                      r.id ?? `${r.seriesName}-${r.issueNumber}-new`;
                    return (
                      <div
                        key={cardKey}
                        className={styles.stripCard}
                        data-testid={`new-series-${cardKey}`}
                      >
                        <div className={styles.spine} style={spineStyle(r)} aria-hidden />
                        <div className={styles.cardBody}>
                          <div className={styles.cardTitle}>{r.seriesName}</div>
                          <div className={styles.cardSub}>{rowSub(r)}</div>
                        </div>
                        <button
                          type="button"
                          className={styles.addBtn}
                          aria-label={`Add ${r.seriesName}`}
                          onClick={() => addNewSeries(r)}
                        >
                          <PlusIcon size={13} />
                          Add
                        </button>
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

            <div data-testid="calendar-agenda">
              {view.days.length === 0 ? (
                <div className={styles.empty}>
                  <div className={styles.emptyIcon} aria-hidden>
                    <i className="fa-solid fa-calendar-day" />
                  </div>
                  <div>No releases this week for that filter.</div>
                </div>
              ) : (
                view.days.map((d) => (
                  <div className={styles.day} key={d.key}>
                    <div className={styles.gutter}>
                      <div
                        className={`${styles.dow} ${
                          d.isNewComicDay ? styles.dowBig : d.isToday ? styles.dowToday : ''
                        }`}
                      >
                        {d.dow}
                      </div>
                      <div
                        className={`${styles.dateNum} ${d.isToday ? styles.dateNumToday : ''}`}
                      >
                        {d.date}
                      </div>
                      <div className={styles.mon}>{d.mon}</div>
                    </div>
                    <div
                      className={`${styles.stream} ${d.isNewComicDay ? styles.streamBig : ''}`}
                    >
                      <div className={styles.dayHeader}>
                        {d.isNewComicDay && (
                          <span className={styles.badgeNcd}>
                            <i className="fa-solid fa-bolt" aria-hidden />
                            New Comic Day
                          </span>
                        )}
                        {d.isToday && <span className={styles.badgeToday}>Today</span>}
                        <span className={styles.count}>
                          {d.count} issue{d.count === 1 ? '' : 's'}
                        </span>
                        {scope === 'all' && d.followed > 0 && (
                          <span className={styles.followed}>
                            <i className="fa-solid fa-bookmark" aria-hidden />
                            {d.followed} followed
                          </span>
                        )}
                      </div>
                      <div className={styles.cards}>
                        {d.releases.map((r) => renderCard(r, d.isFuture))}
                      </div>
                      {scope === 'following' && d.hidden > 0 && (
                        <div className={styles.hidden}>
                          <i className="fa-solid fa-ellipsis" aria-hidden />
                          +{d.hidden} more title{d.hidden === 1 ? '' : 's'} shipping this day
                        </div>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </>
        )}
      </div>
    </>
  );
}
