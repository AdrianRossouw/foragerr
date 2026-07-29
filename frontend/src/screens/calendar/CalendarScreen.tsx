import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Toolbar } from '../../components/Toolbar';
import { SegmentedControl } from '../../components/SegmentedControl';
import {
  BookmarkIcon,
  CheckIcon,
  MoreIcon,
  PlusIcon,
  RefreshIcon,
  SearchIcon,
  SpinnerIcon,
} from '../../components/icons';
import {
  useRunCommand,
  useSeriesIndex,
  useSystemHealth,
  useToggleIssueMonitored,
  useWatchedCommand,
  useWeeklyPull,
} from '../../api/hooks';
import { queryKeys } from '../../api/queryKeys';
import type {
  AddSeriesNavigationState,
  PullEntryRecord,
} from '../../api/types';
import { candidateCoverUrl } from '../../api/urls';
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
 * issue operations; the pull endpoint stays read-only (D4). Every unlinked
 * entry whose series is not already in the library offers an add hand-off —
 * carrying the entry's ComicVine series id when the source supplied one —
 * and new-series debuts render inline with a "New" badge behind an optional
 * debuts-only filter (FRG-PULL-008). Stored covers and enrichment render from
 * the pull row itself, spending no ComicVine budget (FRG-UI-042).
 */

type Scope = 'following' | 'all';

const SCOPE_OPTIONS = [
  { value: 'following' as const, label: 'Following' },
  { value: 'all' as const, label: 'All releases' },
];

/** A well-formed `?week=` param: `YYYY-Www` with a plausible ISO week 01..53. */
const WEEK_PARAM_RE = /^\d{4}-W\d{2}$/;

/**
 * Guard the URL's `?week=` before it reaches the week utilities. A malformed
 * value (`?week=not-a-week`) would otherwise flow into `weekMonday`/`weekDates`
 * and crash the render before the backend's 400 could ever surface — so an
 * invalid param is rejected here and the screen falls back to the current week.
 */
function isValidWeekParam(week: string | null): week is string {
  if (!week || !WEEK_PARAM_RE.test(week)) return false;
  const weekNumber = Number(week.slice(6));
  return weekNumber >= 1 && weekNumber <= 53;
}

/** Casefold a series title for exact library-membership comparison. */
function normalizeTitle(title: string): string {
  return title.trim().toLowerCase();
}

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

/**
 * The card's cover: the entry's stored cover served same-origin through the
 * authenticated proxy (FRG-UI-042), lazily so a ~70-entry week only fetches
 * what the viewport shows. No stored URL — or a fetch that errors — falls back
 * to the publisher-tinted spine, never a broken image.
 */
function CardCover({ r, name }: { r: PullEntryRecord; name: string }) {
  const [failed, setFailed] = useState(false);
  const src = failed ? null : candidateCoverUrl(r.coverUrl);
  if (src === null) {
    return <div className={styles.spine} style={spineStyle(r)} aria-hidden />;
  }
  return (
    <img
      className={styles.cover}
      src={src}
      alt={`${name} cover`}
      loading="lazy"
      style={spineStyle(r)}
      onError={() => setFailed(true)}
    />
  );
}

/** True when an entry has any stored enrichment worth a detail surface. */
function hasDetail(r: PullEntryRecord): boolean {
  return Boolean(
    r.description ||
      r.upc ||
      (r.creators?.length ?? 0) > 0 ||
      (r.characters?.length ?? 0) > 0,
  );
}

/**
 * The expanded entry detail (FRG-UI-042) — the enrichment stored at ingest
 * (FRG-PULL-011), rendered as text (never HTML) with absent fields omitted
 * entirely rather than shown empty. Reads nothing but the pull row, so opening
 * it issues no request at all, ComicVine or otherwise.
 */
function EntryDetail({ r, testId }: { r: PullEntryRecord; testId: string }) {
  const creators = r.creators ?? [];
  const characters = r.characters ?? [];
  return (
    <div className={styles.detail} data-testid={testId}>
      {r.description && <p className={styles.detailDeck}>{r.description}</p>}
      {creators.length > 0 && (
        <div className={styles.detailRow}>
          <span className={styles.detailLabel}>Creators</span>
          <span className={styles.detailValue}>
            {creators
              .map((c) => (c.role ? `${c.name} (${c.role})` : c.name))
              .join(', ')}
          </span>
        </div>
      )}
      {characters.length > 0 && (
        <div className={styles.detailRow}>
          <span className={styles.detailLabel}>Characters</span>
          <span className={styles.detailValue}>
            {characters.map((c) => c.name).join(', ')}
          </span>
        </div>
      )}
      {r.upc && (
        <div className={styles.detailRow}>
          <span className={styles.detailLabel}>UPC</span>
          <span className={styles.detailValue}>{r.upc}</span>
        </div>
      )}
    </div>
  );
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
  const rawWeek = searchParams.get('week');
  const weekParamValid = isValidWeekParam(rawWeek);
  // A malformed param renders the current week (never a crashed utility); the
  // effect below also rewrites the URL so it reflects what is actually shown.
  const week = weekParamValid ? rawWeek : thisWeek;

  useEffect(() => {
    if (rawWeek !== null && !weekParamValid) {
      setSearchParams({}, { replace: true });
    }
  }, [rawWeek, weekParamValid, setSearchParams]);

  const [scope, setScope] = useState<Scope>('all');
  const [publisher, setPublisher] = useState<string>('all');
  // Debuts-only view (FRG-PULL-008): narrows the agenda to the badge-carrying
  // `new_series` entries; off by default, so the week reads whole.
  const [debutsOnly, setDebutsOnly] = useState(false);
  // Cards whose enrichment detail is expanded, keyed by the card key.
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());

  const { data, isLoading, isError } = useWeeklyPull(week);
  const records = useMemo(() => data ?? [], [data]);

  // Weekly-pull-source health (FRG-UI-035): the health payload surfaces a
  // `pull-source` component ONLY when the external source is degraded AND the
  // pull feature is enabled (a disabled or healthy source contributes no
  // component). So the component's mere presence — with a non-OK state — is the
  // gate for the inline notice; a healthy or deliberately-disabled source shows
  // nothing, and the Calendar keeps rendering from local library data.
  const health = useSystemHealth();
  const pullSourceDegraded = (
    Array.isArray(health.data) ? health.data : []
  ).some(
    (component) => component.component === 'pull-source' && component.state !== 'ok',
  );

  // Reuse the cached library index (['series'], shared with HeaderQuickSearch)
  // to suppress a card's add affordance once its series is in the library:
  // after adding, the add flow invalidates ['series'], so returning to the
  // Calendar drops the stale "Add" without waiting for the next pull-refresh
  // to rematch the row (FRG-PULL-008). Exact casefolded-title match only — the
  // imprecision errs toward suppressing an affordance, never toward adding.
  const seriesIndex = useSeriesIndex();
  const libraryTitles = useMemo(() => {
    const titles = new Set<string>();
    for (const s of seriesIndex.data ?? []) {
      if (typeof s.title === 'string') titles.add(normalizeTitle(s.title));
    }
    return titles;
  }, [seriesIndex.data]);

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
    // "Today" is the viewer's LOCAL calendar day (read local y/m/d), so the
    // Today badge lands on the right row for users far from UTC near a day
    // boundary; the store-date keys it compares against are plain dates.
    const now = new Date();
    return isoDateKey(
      new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())),
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

    // Debuts live in the day agenda in date position, badged (FRG-PULL-008) —
    // there is no separate strip to double-count them against.
    // Defensive: a dateless agenda row renders in no day (its releaseDate never
    // equals a day key), so it must not inflate the week/day counts either.
    const agenda = pubFiltered.filter((r) => r.releaseDate != null);

    const weekAll = agenda.length;
    const weekFollowed = agenda.filter(isFollowing).length;
    const debutCount = agenda.filter((r) => r.matchType === 'new_series').length;
    const scoped = scope === 'following' ? agenda.filter(isFollowing) : agenda;
    const visible = debutsOnly
      ? scoped.filter((r) => r.matchType === 'new_series')
      : scoped;

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

    return { publishers, debutCount, weekAll, weekFollowed, days };
  }, [records, publisher, scope, debutsOnly, week, todayKey]);

  // The "across every publisher" scope only holds with no publisher filter; when
  // one is active the count is already scoped to it, so name it (or drop the
  // suffix) rather than claim a breadth that no longer applies.
  const publisherScope =
    publisher === 'all' ? 'across every publisher' : `from ${publisher}`;
  const banner =
    scope === 'following'
      ? `Comics ship in one big weekly drop. You're seeing the ${view.weekFollowed} ` +
        `issue${view.weekFollowed === 1 ? '' : 's'} from series you follow — ` +
        `${view.weekAll - view.weekFollowed} more titles ship this week ${publisherScope}.`
      : `Showing all ${view.weekAll} single issue${view.weekAll === 1 ? '' : 's'} ` +
        `shipping this week${publisher === 'all' ? '' : ` from ${publisher}`} — ` +
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

  /**
   * Hand an entry off to the standard Add flow (FRG-PULL-008). The source's
   * ComicVine series id rides along when the payload carried one, so the Add
   * screen resolves the exact volume instead of asking the operator to redo a
   * search; the name stays as the fallback for an entry without an id — and
   * for an id ComicVine no longer knows. Navigation only: nothing is created
   * until the user completes the add flow.
   */
  const addFromEntry = (r: PullEntryRecord) => {
    const state: AddSeriesNavigationState = {
      prefillCvVolumeId: r.cvSeriesId ?? undefined,
      prefillTerm: r.seriesName,
    };
    navigate('/add', { state });
  };

  const toggleDetail = (cardKey: string) => {
    const next = new Set(expanded);
    if (next.has(cardKey)) next.delete(cardKey);
    else next.add(cardKey);
    setExpanded(next);
  };

  /**
   * One release card. Linked rows (matchedIssueId set) expose want/skip +
   * search; unlinked rows show their derived-state glyph (FRG-PULL-007) and,
   * when nothing links them to the library and their title is not already
   * there, the add affordance (FRG-PULL-008). Any entry carrying stored
   * enrichment also offers the detail expando (FRG-UI-042).
   */
  const renderCard = (r: PullEntryRecord, isFuture: boolean) => {
    const linked = r.matchedIssueId != null;
    const monitored = r.state !== 'unmonitored';
    const name = rowName(r);
    const cardKey = String(
      r.id ?? `${r.seriesName}-${r.issueNumber}-${r.matchedIssueId}`,
    );
    const isDebut = r.matchType === 'new_series';
    // Guard-failed rows for a series already in the library self-heal on the
    // next refresh — offering "Add" there would invite duplicates.
    const canAdd =
      !linked &&
      (r.matchType === 'unmatched' || isDebut) &&
      !libraryTitles.has(normalizeTitle(r.seriesName));
    const detailOpen = expanded.has(cardKey);
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
        <div className={styles.cardRow}>
          <CardCover r={r} name={name} />
          <div className={styles.cardBody}>
            <div className={styles.cardTitle}>
              <span className={styles.cardTitleText}>{name}</span>
              {isDebut && (
                <span
                  className={styles.badgeNew}
                  data-testid={`calendar-new-badge-${cardKey}`}
                >
                  New
                </span>
              )}
            </div>
            <div className={styles.cardSub}>{rowSub(r)}</div>
            {isFuture && <div className={styles.unreleased}>Not yet released</div>}
          </div>
          <div className={styles.actions}>
            {canAdd && (
              <button
                type="button"
                className={styles.addBtn}
                aria-label={`Add ${r.seriesName}`}
                onClick={() => addFromEntry(r)}
              >
                <PlusIcon size={13} />
                Add
              </button>
            )}
            {hasDetail(r) && (
              <button
                type="button"
                className={styles.iconBtn}
                aria-label={`${detailOpen ? 'Hide' : 'Show'} details for ${name}`}
                aria-expanded={detailOpen}
                title="Details"
                onClick={() => toggleDetail(cardKey)}
              >
                <MoreIcon size={13} />
              </button>
            )}
            {linked ? (
              <>
                <button
                  type="button"
                  className={styles.iconBtn}
                  aria-label={`${monitored ? 'Skip' : 'Want'} ${name}`}
                  title={monitored ? 'Stop monitoring' : 'Monitor / want'}
                  onClick={() =>
                    toggle.mutate({
                      issueId: r.matchedIssueId as number,
                      monitored: !monitored,
                    })
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
              </>
            ) : (
              <StateGlyph state={r.state} />
            )}
          </div>
        </div>
        {detailOpen && (
          <EntryDetail r={r} testId={`calendar-detail-${cardKey}`} />
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
            <button
              type="button"
              className={styles.filterToggle}
              data-active={debutsOnly}
              aria-pressed={debutsOnly}
              title="Show only this week's new-series debuts"
              onClick={() => setDebutsOnly((v) => !v)}
            >
              New series only
              {view.debutCount > 0 && (
                <span className={styles.filterCount}>{view.debutCount}</span>
              )}
            </button>
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

        {pullSourceDegraded && (
          <div
            className={styles.degradedNotice}
            role="status"
            data-testid="calendar-degraded-notice"
          >
            <i
              className={`fa-solid fa-triangle-exclamation ${styles.degradedNoticeIcon}`}
              aria-hidden
            />
            <span>
              The weekly pull source is currently unavailable — the Calendar is
              showing your library&rsquo;s own data only.
            </span>
          </div>
        )}

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
                        className={`${styles.dateNum} ${
                          d.isToday
                            ? styles.dateNumToday
                            : d.isNewComicDay
                              ? styles.dateNumBig
                              : ''
                        }`}
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
