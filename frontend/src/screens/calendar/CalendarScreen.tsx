import { memo, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Toolbar } from '../../components/Toolbar';
import { SegmentedControl } from '../../components/SegmentedControl';
import { Chip, type ChipTone } from '../../components/Chip';
import { stripHtml } from '../add/AddSeries';
import {
  BookmarkIcon,
  MoreIcon,
  PlusIcon,
  SearchIcon,
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
  PullEntryState,
} from '../../api/types';
import { candidateCoverUrl } from '../../api/urls';
import { publisherAccent, publisherTint } from '../../theme/palettes';
import { useCompactViewport } from '../../theme/useCompactViewport';
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
 *
 * Entries present in one of two modes selected by the single compact crossover
 * (theme/layout.ts): dense agenda rows at or above it, quiet single-column
 * cards with an icon-only action rail below it. Both modes render the same data
 * and expose the same action SET — nothing is reachable in one and not the
 * other — so the mode is a presentation choice, never a capability boundary.
 */

type Scope = 'following' | 'all';

/** Which of FRG-UI-018's two entry presentations is rendering. */
type EntryMode = 'row' | 'card';

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

/**
 * Derived state as words + a chip tone (FRG-UI-047). The label is the state's
 * only rendering: a status carries no glyph that also denotes a control on this
 * surface, so the bookmark stays exclusive to the real monitor toggle. The
 * wanted state takes the amber warning tone a missing released issue already
 * carries on the series screen, so one state does not read two ways; amber is a
 * semantic status hue, never the accent that marks an active toggle.
 */
const STATE_PRESENTATION: Record<PullEntryState, { label: string; tone: ChipTone }> = {
  missing_wanted: { label: 'Wanted', tone: 'warning' },
  downloading: { label: 'Downloading', tone: 'info' },
  downloaded: { label: 'Downloaded', tone: 'success' },
  unmonitored: { label: 'Not tracked', tone: 'muted' },
  pending_refresh: { label: 'Pending refresh', tone: 'muted' },
};

/** An entry linked to no library issue has no derived state to project. */
const UNLINKED_PRESENTATION: { label: string; tone: ChipTone } = {
  label: 'Not in library',
  tone: 'muted',
};

/**
 * The class each shared entry part takes in each mode. Held as one bundle per
 * mode so a part cannot be styled as a row in one place and a card in another:
 * every mode-dependent class an entry uses is named here, and the modes must
 * carry the same keys.
 */
const ENTRY_CLASSES: Record<
  EntryMode,
  {
    root: string;
    actions: string;
    titleWrap: string;
    titleText: string;
    meta: string;
    thumb: string;
  }
> = {
  row: {
    root: styles.row,
    actions: styles.rowActions,
    titleWrap: styles.rowTitle,
    titleText: styles.rowTitleText,
    meta: styles.rowMeta,
    thumb: styles.thumbRow,
  },
  card: {
    root: styles.card,
    actions: styles.cardRail,
    titleWrap: styles.cardTitle,
    titleText: styles.cardTitleText,
    meta: styles.cardMeta,
    thumb: styles.thumbCard,
  },
};

/**
 * Why a monitor-on that the backend accepted left the entry untracked, or null
 * when it did take (FRG-UI-048). A 200 does not mean the entry changed: the
 * projected state answers to the SERIES' monitored flag as well as the issue's.
 *
 * This reads a CAUSE out of an effect, which holds only while the projection has
 * exactly one route to `unmonitored` — the backend's `_derive_issue_state`
 * (backend/src/foragerr/pull/projection.py) returns it for a monitored flag that
 * is off and for nothing else. A second route would have to carry its own
 * signal; inferring from this state would then misattribute it.
 */
function monitorRefusalReason(
  requested: boolean,
  settledState: PullEntryState | null | undefined,
): string | null {
  if (!requested || settledState !== 'unmonitored') return null;
  return (
    'The change was saved, but this issue stays untracked because its series ' +
    'is not monitored. Monitor the series to start tracking its issues.'
  );
}

/**
 * The entry's state as a status indicator (FRG-UI-047): a plain chip `<span>` —
 * no button role, no `aria-pressed`, not focusable, no pointer cursor and no
 * control hover treatment — whose meaning is the text inside it, so assistive
 * technology announces state rather than an operable element.
 */
function StatusChip({
  state,
  testId,
}: {
  state: PullEntryState | null;
  testId: string;
}) {
  const { label, tone } = state === null ? UNLINKED_PRESENTATION : STATE_PRESENTATION[state];
  return (
    <Chip tone={tone} testId={testId} className={styles.stateChip}>
      {label}
    </Chip>
  );
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
// Memoized so a single card interaction (expando toggle, want/skip) on the
// parent doesn't re-render every sibling's cover across a full week's agenda.
const CardCover = memo(function CardCover({
  r,
  name,
  mode,
}: {
  r: PullEntryRecord;
  name: string;
  /** Agenda rows carry a smaller fixed thumbnail than cards, for row density. */
  mode: EntryMode;
}) {
  const [failed, setFailed] = useState(false);
  const sizeClass = ENTRY_CLASSES[mode].thumb;
  const src = failed ? null : candidateCoverUrl(r.coverUrl);
  if (src === null) {
    return (
      <div
        className={`${styles.spine} ${sizeClass}`}
        style={spineStyle(r)}
        aria-hidden
      />
    );
  }
  return (
    <img
      className={`${styles.cover} ${sizeClass}`}
      src={src}
      alt={`${name} cover`}
      loading="lazy"
      style={spineStyle(r)}
      onError={() => setFailed(true)}
    />
  );
});

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
 * it issues no request at all, ComicVine or otherwise. The description is the
 * same untrusted ComicVine deck the Add-series candidate card renders, so it
 * runs through the identical `stripHtml` before display (never dangerouslySet).
 */
function EntryDetail({ r, id }: { r: PullEntryRecord; id: string }) {
  const creators = r.creators ?? [];
  const characters = r.characters ?? [];
  const description = r.description ? stripHtml(r.description) : '';
  return (
    <div className={styles.detail} id={id} data-testid={id}>
      {description && <p className={styles.detailDeck}>{description}</p>}
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

  // One crossover for the whole app (theme/layout.ts): rows above it, cards
  // below it, and the shell's sidebar collapses at exactly the same width.
  const compact = useCompactViewport();
  const mode: EntryMode = compact ? 'card' : 'row';

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

  // Want/skip and search both write through the canonical issue operations, so
  // either can be refused (a read-only series' issue answers 409). Report the
  // refusal in one alert region: a silently-rejected toggle is indistinguishable
  // from a bookmark that simply did not stick.
  //
  // The toggle's failure is held in local state rather than read off
  // `toggle.error`: one mutation observer serves every row, and a later
  // activation replaces the observer's result, so a concurrent toggle would
  // erase a refusal before the operator ever saw it.
  const [monitorError, setMonitorError] = useState<string | null>(null);
  const actionError = monitorError ?? runCommand.error?.message ?? null;

  // Monitor toggles in flight, keyed by issue id and holding the REQUESTED
  // monitored value (FRG-UI-048). The optimistic value is dropped only once the
  // re-projection that replaces it has landed, so the control never flashes back
  // to the stale state between the response and the refetch; a key present here
  // also suppresses a second mutation for that entry.
  const [requestedMonitor, setRequestedMonitor] = useState<
    ReadonlyMap<number, boolean>
  >(new Map());
  // Admission control for the same map, mutated synchronously: the state value a
  // handler closes over is the one its render was bound with, so two activations
  // inside a single frame would both pass a check made against it. A ref is
  // updated the moment the first one is admitted.
  const inFlightMonitor = useRef<Set<number>>(new Set());

  const settleMonitor = (issueId: number) => {
    inFlightMonitor.current.delete(issueId);
    setRequestedMonitor((prev) => {
      if (!prev.has(issueId)) return prev;
      const next = new Map(prev);
      next.delete(issueId);
      return next;
    });
  };

  const toggleMonitor = async (issueId: number, monitored: boolean) => {
    if (inFlightMonitor.current.has(issueId)) return;
    inFlightMonitor.current.add(issueId);
    setRequestedMonitor((prev) => new Map(prev).set(issueId, monitored));
    setMonitorError(null);
    try {
      // `mutateAsync` and not `mutate`: the per-call `onSuccess`/`onSettled`
      // callbacks live on the shared observer, so a second row's activation
      // discards this one's — leaving its optimistic value in the map forever
      // (a permanently busy, dead control) and swallowing its failure. Only the
      // returned promise is per-call.
      await toggle.mutateAsync({ issueId, monitored });
      // Awaited, so the requested value stays on screen until the re-projection
      // that supersedes it has landed (FRG-UI-048): clearing it any earlier
      // shows the pre-toggle state again for the length of a refetch.
      await queryClient.invalidateQueries({ queryKey: queryKeys.pull.all() });
      // Read from the re-projection, not from the response: without this the
      // bookmark simply snaps back — indistinguishable from a click that did
      // nothing, which FRG-UI-048 forbids.
      const settledState = (
        queryClient.getQueryData<PullEntryRecord[]>(queryKeys.pull.week(week)) ?? []
      ).find((r) => r.matchedIssueId === issueId)?.state;
      const refusal = monitorRefusalReason(monitored, settledState);
      if (refusal !== null) setMonitorError(refusal);
    } catch (error) {
      setMonitorError(error instanceof Error ? error.message : String(error));
    } finally {
      settleMonitor(issueId);
    }
  };

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

    // Whole-week totals (publisher-filtered, but ignoring scope/debutsOnly) —
    // these back the "N more titles ship" / "N from series you follow" side of
    // the banner, which is about the scope toggle, not the debuts filter.
    const weekAll = agenda.length;
    const weekFollowed = agenda.filter(isFollowing).length;
    const scoped = scope === 'following' ? agenda.filter(isFollowing) : agenda;
    // Debuts in the CURRENT scope, not the whole week: a `new_series` entry is
    // never "following" (no matched issue -> no series -> isFollowing false),
    // so this is always 0 in Following scope — the toggle renders only when
    // this is > 0, rather than advertise a count that yields an empty view.
    const debuts = scoped.filter((r) => r.matchType === 'new_series');
    const debutCount = debuts.length;
    const visible = debutsOnly ? debuts : scoped;
    // What is actually rendered once publisher + scope + debutsOnly all
    // compose — the banner's headline figure must match this count, never a
    // pre-debutsOnly-filter total (publisher + scope alone).
    const renderedCount = visible.length;

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

    return { publishers, debutCount, weekAll, weekFollowed, renderedCount, days };
  }, [records, publisher, scope, debutsOnly, week, todayKey]);

  // The "across every publisher" scope only holds with no publisher filter; when
  // one is active the count is already scoped to it, so name it (or drop the
  // suffix) rather than claim a breadth that no longer applies.
  const publisherScope =
    publisher === 'all' ? 'across every publisher' : `from ${publisher}`;
  // The headline figure is `renderedCount` — what publisher + scope + debutsOnly
  // together actually put on screen — never the pre-debutsOnly-filter total, so
  // the banner never claims a count larger than what's rendered underneath it.
  const banner =
    scope === 'following'
      ? `Comics ship in one big weekly drop. You're seeing the ${view.renderedCount} ` +
        `issue${view.renderedCount === 1 ? '' : 's'} from series you follow — ` +
        `${view.weekAll - view.weekFollowed} more titles ship this week ${publisherScope}.`
      : `Showing all ${view.renderedCount} single issue${view.renderedCount === 1 ? '' : 's'} ` +
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
   * One entry, in whichever of FRG-UI-018's two presentations is active. Linked
   * entries (matchedIssueId set) expose want/skip + search; an unlinked entry
   * whose series is not already in the library exposes the add hand-off
   * (FRG-PULL-008), and any entry carrying stored enrichment exposes the detail
   * expando (FRG-UI-042). The action SET is computed once and rendered
   * identically in both modes — only its placement differs, so no affordance can
   * exist on one side of the crossover and not the other.
   *
   * Every action is icon-only in BOTH modes. A labelled Add is roughly three
   * times an icon button's width in the same fixed cluster, and on a row that
   * width comes straight off the title's measure — the one element the screen
   * exists to let the operator scan.
   */
  const renderEntry = (r: PullEntryRecord, isFuture: boolean) => {
    const linked = r.matchedIssueId != null;
    const issueId = r.matchedIssueId;
    const name = rowName(r);
    // Whitespace is collapsed out: the fallback key is built from a series name,
    // and this value becomes a DOM id that `aria-controls` points at — where a
    // space would be read as a separator between two ids, neither of which exists.
    const cardKey = String(
      r.id ?? `${r.seriesName}-${r.issueNumber}-${r.matchedIssueId}`,
    ).replace(/\s+/g, '_');
    const isDebut = r.matchType === 'new_series';
    // Guard-failed rows for a series already in the library self-heal on the
    // next refresh — offering "Add" there would invite duplicates.
    const canAdd =
      !linked &&
      (r.matchType === 'unmatched' || isDebut) &&
      !libraryTitles.has(normalizeTitle(r.seriesName));
    const detailOpen = expanded.has(cardKey);
    const detailId = `calendar-detail-${cardKey}`;
    // The requested value wins while a mutation is in flight, so activation
    // reads as done at once instead of dead until the refetch (FRG-UI-048).
    const inFlight = issueId != null && requestedMonitor.has(issueId);
    const monitored =
      inFlight && issueId != null
        ? (requestedMonitor.get(issueId) as boolean)
        : r.state !== 'unmonitored';
    const v = ENTRY_CLASSES[mode];
    const cls = [
      v.root,
      linked ? '' : styles.entryUnlinked,
      isFuture ? styles.entryFuture : '',
    ]
      .filter(Boolean)
      .join(' ');

    const actions = (
      <div className={v.actions}>
        {canAdd && (
          <button
            type="button"
            className={`${styles.iconBtn} ${styles.iconBtnPrimary}`}
            aria-label={`Add ${r.seriesName}`}
            title="Add series"
            onClick={() => addFromEntry(r)}
          >
            <PlusIcon size={14} />
          </button>
        )}
        {hasDetail(r) && (
          <button
            type="button"
            className={styles.iconBtn}
            aria-label={`${detailOpen ? 'Hide' : 'Show'} details for ${name}`}
            aria-expanded={detailOpen}
            // Only while the panel exists: `aria-controls` pointing at an
            // absent id is an invalid reference, not a hint.
            aria-controls={detailOpen ? detailId : undefined}
            title="Details"
            onClick={() => toggleDetail(cardKey)}
          >
            <MoreIcon size={14} />
          </button>
        )}
        {linked && issueId != null && (
          <>
            {/* The bookmark glyph renders ONLY here — on the real toggle
                (FRG-UI-047). The accessible name is state-NEUTRAL because
                `aria-pressed` already carries the state: an action-phrased name
                ("Skip …") pairs with pressed to announce the inverse of the
                truth. The action wording stays on `title`, for sighted hover.
                In flight the control is `aria-disabled`, not `disabled`, so it
                keeps its place in keyboard order mid-interaction; the duplicate
                mutation is suppressed in the handler. `aria-busy` is what makes
                that unavailability read as work in progress rather than as a
                control that has been switched off. */}
            <button
              type="button"
              className={`${styles.iconBtn}${inFlight ? ` ${styles.iconBtnBusy}` : ''}`}
              aria-label={`Monitor ${name}`}
              aria-pressed={monitored}
              aria-disabled={inFlight}
              aria-busy={inFlight}
              title={monitored ? 'Stop monitoring' : 'Monitor / want'}
              onClick={() => void toggleMonitor(issueId, !monitored)}
            >
              <BookmarkIcon size={14} filled={monitored} />
            </button>
            {/* One watched command backs the status chip, so only one search
                runs at a time. `aria-disabled` rather than `disabled`: the
                running flag is screen-wide, and disabling the focused button
                would drop focus to the document body mid-agenda. */}
            <button
              type="button"
              className={styles.iconBtn}
              aria-label={`Search for ${name}`}
              title="Automatic search"
              aria-disabled={command.running}
              onClick={() => {
                if (command.running) return;
                dispatchSearch(r);
              }}
            >
              <SearchIcon size={14} />
            </button>
          </>
        )}
      </div>
    );

    const title = (
      <div className={v.titleWrap}>
        <span className={v.titleText}>{name}</span>
        {isDebut && (
          <span
            className={styles.badgeNew}
            data-testid={`calendar-new-badge-${cardKey}`}
          >
            New
          </span>
        )}
      </div>
    );

    // The not-yet-released marking is a property of the DAY, not the entry (a
    // store date is in the future for every entry in that group), so it is
    // stated once in the day header. Repeating it per entry would put a ~110px
    // nowrap token in the row's meta track, and the title's measure is what
    // pays for it (FRG-UI-018).
    const meta = (
      <div className={v.meta}>
        <span className={styles.metaText}>{rowSub(r)}</span>
        <StatusChip state={r.state} testId={`calendar-state-${cardKey}`} />
      </div>
    );

    /* Keyed on the cover URL, not just cardKey: the entry's `failed` flag lives
       inside CardCover's own state, so a refetch that repairs a previously-broken
       cover under the SAME row id needs a changed key here to remount the
       component and reset `failed` — otherwise the stale flag keeps forcing the
       spine even once the URL is good. */
    const cover = (
      <CardCover key={r.coverUrl ?? 'none'} r={r} name={name} mode={mode} />
    );

    return (
      <li
        key={cardKey}
        className={cls}
        data-testid={`calendar-card-${cardKey}`}
        data-mode={mode}
        data-linked={linked}
        data-future={isFuture}
      >
        {mode === 'row' ? (
          <div className={styles.rowFace}>
            {cover}
            {title}
            {meta}
            {actions}
          </div>
        ) : (
          <>
            <div className={styles.cardFace}>
              {cover}
              <div className={styles.cardBody}>
                {title}
                {meta}
              </div>
            </div>
            {actions}
          </>
        )}
        {detailOpen && <EntryDetail r={r} id={detailId} />}
      </li>
    );
  };

  return (
    <>
      <Toolbar
        title="Calendar"
        actions={
          <span className={styles.toolbarActions}>
            {/* The running search disables no row's button visibly on its own,
                so its progress is announced instead of only drawn. */}
            {commandLabel && command.status && (
              <span
                className={styles.commandChip}
                role="status"
                data-testid="command-status"
              >
                {commandLabel}: {command.status}
              </span>
            )}
            {/* A debut-free scope must not offer a filter that yields the empty
                state (restores the retired "no new-series -> no strip"
                behavior at the toggle level): only render it when the CURRENT
                scope actually has a debut to narrow to. */}
            {view.debutCount > 0 && (
              <button
                type="button"
                className={styles.filterToggle}
                data-active={debutsOnly}
                aria-pressed={debutsOnly}
                title="Show only this week's new-series debuts"
                onClick={() => setDebutsOnly((v) => !v)}
              >
                New series only
                <span className={styles.filterCount}>{view.debutCount}</span>
              </button>
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
      <div className={styles.screen} data-compact={compact ? 'true' : 'false'}>
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

        {actionError && (
          <p
            className={styles.actionError}
            role="alert"
            data-testid="calendar-action-error"
          >
            {actionError}
          </p>
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
                  <div
                    className={compact ? styles.dayCompact : styles.day}
                    key={d.key}
                    data-testid={`calendar-day-${d.key}`}
                  >
                    {/* The 72px gutter costs a narrow viewport 114px of chrome it
                        cannot spare, so below the crossover the date folds into
                        the day header instead of holding a fixed column.
                        Hidden from the accessibility tree: it draws the same date
                        the day heading carries, as three separate boxes, so left
                        exposed it makes assistive technology read every date in
                        the week twice. */}
                    {!compact && (
                      <div className={styles.gutter} aria-hidden="true">
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
                    )}
                    <div
                      className={
                        compact
                          ? styles.streamCompact
                          : `${styles.stream} ${d.isNewComicDay ? styles.streamBig : ''}`
                      }
                    >
                      {/* A heading, so the day groups are structure a screen
                          reader can jump between rather than styled text: a
                          drop day runs to dozens of entries. Wide mode draws the
                          date in the hidden gutter, so the heading is the only
                          place it is announced. */}
                      <h2 className={styles.dayHeader}>
                        {compact ? (
                          <span
                            className={styles.dayInlineDate}
                            data-testid={`calendar-day-inline-${d.key}`}
                          >
                            {d.dow} {d.date} {d.mon}
                          </span>
                        ) : (
                          // The wide-mode gutter draws this same date as three
                          // separate boxes and is hidden from the accessibility
                          // tree, so this is the one place it is announced.
                          <span className="sr-only">
                            {`${d.dow} ${d.date} ${d.mon}`}
                          </span>
                        )}
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
                          // Not a bookmark: that glyph belongs to the monitor
                          // toggle on this surface, and FRG-UI-047 keeps a
                          // non-interactive indicator off a control's glyph.
                          <span className={styles.followed}>
                            <i className="fa-solid fa-eye" aria-hidden />
                            {d.followed} followed
                          </span>
                        )}
                        {d.isFuture && (
                          <span
                            className={styles.unreleased}
                            data-testid={`calendar-unreleased-${d.key}`}
                          >
                            Not yet released
                          </span>
                        )}
                      </h2>
                      <ul className={compact ? styles.cards : styles.rows}>
                        {d.releases.map((r) => renderEntry(r, d.isFuture))}
                      </ul>
                      {scope === 'following' && d.hidden > 0 && (
                        // No glyph: the details control on this same surface
                        // draws an identical ellipsis (FRG-UI-047).
                        <div className={styles.hidden}>
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
