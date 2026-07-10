import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Toolbar } from '../../components/Toolbar';
import { ToolbarButton } from '../../components/ToolbarButton';
import { ProgressStrip } from '../../components/ProgressStrip';
import { Chip } from '../../components/Chip';
import { Menu } from '../../components/Menu';
import { SegmentedControl } from '../../components/SegmentedControl';
import { Poster } from '../../components/Poster';
import { BookTypeBadge } from '../../components/BookTypeBadge';
import {
  BookmarkIcon,
  BookOpenIcon,
  CheckIcon,
  FilterIcon,
  GridIcon,
  ImportIcon,
  LayersIcon,
  PlusIcon,
  RowsIcon,
  SlidersIcon,
  SortIcon,
  TableIcon,
} from '../../components/icons';
import {
  useSeriesGroups,
  useSeriesIndex,
  useUpdateSeriesGroup,
} from '../../api/hooks';
import { coverUrl } from '../../api/urls';
import { publisherTint } from '../../theme/palettes';
import {
  useUiStore,
  type LibraryCollectedFilter,
  type LibraryPosterSize,
  type LibrarySortKey,
  type LibraryStatusFilter,
  type LibraryViewMode,
} from '../../store/uiStore';
import type { SeriesGroupResource, SeriesResource } from '../../api/types';
import styles from './LibraryIndex.module.css';

/**
 * Library index (FRG-UI-003 / FRG-UI-021): the M4 redesign of the Sonarr-shaped
 * series index. Three view modes — Posters (auto-fill card grid with S/M/L
 * sizes), Overview (rich rows), Table (dense rows) — plus an orthogonal
 * group-volumes overlay that stacks a franchise's runs into one card (poster)
 * or a collapsible header (row/table). The toolbar carries the view switcher and
 * three raised menus (Options / Sort / Filter) plus a text filter; a count line
 * summarizes the library. Posters come EXCLUSIVELY from the LOCAL cover-cache
 * endpoint — never an external ComicVine host. Colors flow through the token
 * layer / publisher-palette data maps (FRG-UI-002); no component hardcodes a hex.
 */

/** S/M/L poster card min-width (px) feeding the auto-fill grid. */
const POSTER_SIZE_PX: Record<LibraryPosterSize, number> = { s: 134, m: 162, l: 196 };

/** A series' continuing/ended status label (design: status === 'continuing'). */
function statusLabel(series: SeriesResource): 'Continuing' | 'Ended' {
  return series.status === 'continuing' ? 'Continuing' : 'Ended';
}

/** Poster / row subline. No writer data exists, so it reads `Status · Year`. */
function subline(series: SeriesResource): string {
  const label = statusLabel(series);
  return series.start_year ? `${label} · ${series.start_year}` : label;
}

function sortSeries(
  records: readonly SeriesResource[],
  sortKey: LibrarySortKey,
): SeriesResource[] {
  const byTitle = (a: SeriesResource, b: SeriesResource) =>
    a.sort_title.localeCompare(b.sort_title);
  const sorted = [...records];
  switch (sortKey) {
    case 'publisher':
      sorted.sort(
        (a, b) =>
          (a.publisher ?? '￿').localeCompare(b.publisher ?? '￿') ||
          byTitle(a, b),
      );
      break;
    case 'issues':
      // Most issues owned first.
      sorted.sort(
        (a, b) => b.statistics.file_count - a.statistics.file_count || byTitle(a, b),
      );
      break;
    case 'year':
      // Newest start year first.
      sorted.sort(
        (a, b) =>
          (b.start_year ?? -Infinity) - (a.start_year ?? -Infinity) || byTitle(a, b),
      );
      break;
    default:
      sorted.sort(byTitle);
  }
  return sorted;
}

/**
 * Collected-editions partition (FRG-UI-022): `collected` keeps only typed
 * series (any non-null book-type), `singles` keeps only null-typed
 * single-issues runs, `all` keeps everything. Display-only.
 */
function matchesCollected(
  series: SeriesResource,
  filter: LibraryCollectedFilter,
): boolean {
  if (filter === 'collected') return series.booktype !== null;
  if (filter === 'singles') return series.booktype === null;
  return true;
}

/** Status partition (FRG-UI-003) — display-only, mirrors the Filter menu. */
function matchesStatus(series: SeriesResource, filter: LibraryStatusFilter): boolean {
  switch (filter) {
    case 'monitored':
      return series.monitored;
    case 'missing':
      return series.statistics.missing_count > 0;
    case 'continuing':
      return series.status === 'continuing';
    default:
      return true;
  }
}

function matchesText(series: SeriesResource, needle: string): boolean {
  return needle ? series.title.toLowerCase().includes(needle) : true;
}

/* --- shared cover chrome --------------------------------------------------- */

/** The bookmark + top-right chip overlay shared by flat and stacked cards. */
function CoverChrome({
  monitored,
  topRight,
}: {
  monitored: boolean;
  topRight: ReactNode;
}) {
  return (
    <>
      <span
        className={styles.monitorChip}
        data-monitored={monitored}
        aria-label={monitored ? 'Monitored' : 'Unmonitored'}
      >
        <BookmarkIcon filled={monitored} size={13} />
      </span>
      <span className={styles.topRightChips}>{topRight}</span>
    </>
  );
}

/* --- flat poster card ------------------------------------------------------ */

function PosterCard({ series }: { series: SeriesResource }) {
  const { statistics: stats } = series;
  return (
    <Link
      to={`/series/${series.id}`}
      className={styles.card}
      id={`series-card-${series.id}`}
      data-testid="series-card"
    >
      <div className={styles.coverRegion}>
        <Poster
          initial={series.title.charAt(0)}
          src={coverUrl(series.id)}
          alt={`${series.title} cover`}
          tint={publisherTint(series.publisher)}
          overlay
          frameClassName={styles.posterFrame}
          fallbackClassName={styles.posterFallback}
          lazy
        />
        <CoverChrome
          monitored={series.monitored}
          topRight={
            <>
              {series.publisher && <Chip tone="overlay">{series.publisher}</Chip>}
              <BookTypeBadge booktype={series.booktype} />
            </>
          }
        />
      </div>
      <ProgressStrip
        have={stats.file_count}
        total={stats.issue_count}
        monitored={series.monitored}
        variant="strip"
      />
      <div className={styles.cardFooter}>
        <span className={styles.cardTitle} title={series.title}>
          {series.title}
        </span>
        <span className={styles.cardSubline}>{subline(series)}</span>
      </div>
    </Link>
  );
}

/* --- overview row (flat) --------------------------------------------------- */

function OverviewRow({ series }: { series: SeriesResource }) {
  const { statistics: stats } = series;
  const cont = statusLabel(series) === 'Continuing';
  const total = stats.issue_count;
  const pct = total > 0 ? Math.round((Math.min(stats.file_count, total) / total) * 100) : 0;
  return (
    <Link
      to={`/series/${series.id}`}
      className={styles.overviewRow}
      data-testid="series-row"
    >
      <Poster
        initial={series.title.charAt(0)}
        src={coverUrl(series.id)}
        alt={`${series.title} cover`}
        tint={publisherTint(series.publisher)}
        frameClassName={styles.overviewThumb}
        fallbackClassName={styles.overviewThumbFallback}
        lazy
      />
      <div className={styles.overviewBody}>
        <div className={styles.overviewTitleRow}>
          <span className={styles.rowMonitor} data-monitored={series.monitored}>
            <BookmarkIcon filled={series.monitored} size={13} />
          </span>
          <span className={styles.overviewTitle} title={series.title}>
            {series.title}
          </span>
          <Chip tone={cont ? 'success' : 'muted'}>{statusLabel(series)}</Chip>
          <BookTypeBadge booktype={series.booktype} />
        </div>
        <div className={styles.overviewMeta}>
          {series.publisher ? `${series.publisher} · ` : ''}
          {subline(series)}
        </div>
        <div className={styles.overviewProgress}>
          <ProgressStrip
            have={stats.file_count}
            total={total}
            monitored={series.monitored}
            variant="bar"
            className={styles.overviewBar}
          />
          <span className={styles.pctText}>{pct}% complete</span>
        </div>
      </div>
    </Link>
  );
}

/* --- table row (flat) ------------------------------------------------------ */

function SeriesTableRow({ series }: { series: SeriesResource }) {
  const { statistics: stats } = series;
  const cont = statusLabel(series) === 'Continuing';
  return (
    <tr data-testid="series-row">
      <td className={styles.iconCol}>
        <span className={styles.rowMonitor} data-monitored={series.monitored}>
          <BookmarkIcon filled={series.monitored} size={14} />
        </span>
      </td>
      <td>
        <span className={styles.tableTitleCell}>
          <Link className={styles.titleLink} to={`/series/${series.id}`}>
            {series.title}
          </Link>
          <BookTypeBadge booktype={series.booktype} />
        </span>
      </td>
      <td>{series.publisher ?? '—'}</td>
      <td>
        <ProgressStrip
          have={stats.file_count}
          total={stats.issue_count}
          monitored={series.monitored}
          variant="mini"
        />
      </td>
      <td>
        <span className={cont ? styles.statusContinuing : styles.statusEnded}>
          {statusLabel(series)}
        </span>
      </td>
      <td className={styles.yearCol}>{series.start_year ?? '—'}</td>
    </tr>
  );
}

function SeriesTable({ children }: { children: ReactNode }) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table} data-testid="library-table">
        <thead>
          <tr>
            <th className={styles.iconCol} aria-label="Monitored" />
            <th>Title</th>
            <th>Publisher</th>
            <th>Issues</th>
            <th>Status</th>
            <th className={styles.yearCol}>Year</th>
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

/* --- franchise rename / reassign affordance (FRG-SER-017) ------------------ */

/**
 * Rename / reassign menu (FRG-SER-017). Rename targets the group via any member
 * (PUTs against a member series id); detach reassigns one run out of the group.
 * Both go through the shared group-edit mutation, which refreshes the flat index
 * + the grouping projection on success.
 */
function FranchiseMenu({
  group,
  members,
  onDone,
}: {
  group: SeriesGroupResource;
  members: SeriesResource[];
  onDone: () => void;
}) {
  const [title, setTitle] = useState(group.title);
  const mutation = useUpdateSeriesGroup();
  const anchor = members[0];

  const submitRename = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = title.trim();
    if (!trimmed || !anchor) return;
    mutation.mutate(
      { seriesId: anchor.id, group: { action: 'rename', title: trimmed } },
      { onSuccess: onDone },
    );
  };

  return (
    <div className={styles.franchiseMenu} role="menu" data-testid="franchise-menu">
      <form className={styles.renameRow} onSubmit={submitRename}>
        <input
          className={styles.renameInput}
          aria-label="Rename franchise"
          data-testid="franchise-rename-input"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <button
          type="submit"
          className={styles.menuAction}
          data-testid="franchise-rename-submit"
          disabled={mutation.isPending}
        >
          Rename
        </button>
      </form>
      <ul className={styles.detachList}>
        {members.map((s) => (
          <li key={s.id}>
            <button
              type="button"
              className={styles.menuAction}
              data-testid={`franchise-detach-${s.id}`}
              disabled={mutation.isPending}
              onClick={() =>
                mutation.mutate(
                  { seriesId: s.id, group: { action: 'detach' } },
                  { onSuccess: onDone },
                )
              }
            >
              Detach {s.title}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * The ⋯ trigger + rename/reassign popover, reused on the stacked poster card and
 * the row/table franchise header. Dismisses on outside pointer-down or Escape
 * (matching the shared Menu pattern), and stops propagation so opening it never
 * fires the enclosing card's navigation.
 */
function FranchiseMenuButton({
  group,
  members,
}: {
  group: SeriesGroupResource;
  members: SeriesResource[];
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div
      className={styles.franchiseMenuWrap}
      ref={wrapRef}
      onClick={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        className={styles.menuButton}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Franchise actions"
        data-testid="franchise-group-menu"
        onClick={(e) => {
          e.stopPropagation();
          e.preventDefault();
          setOpen((v) => !v);
        }}
      >
        ⋯
      </button>
      {open && (
        <FranchiseMenu group={group} members={members} onDone={() => setOpen(false)} />
      )}
    </div>
  );
}

/* --- grouped poster: stacked card ------------------------------------------ */

/**
 * A multi-run franchise as ONE stacked poster card (FRG-UI-021): layered
 * offset-shadow, an `N vols` accent chip, summed owned/total on the strip, and
 * cover/tint/publisher taken from the NEWEST member resolved in the flat cache.
 * The whole card opens the newest member's detail; the ⋯ affordance stops
 * propagation so grouping stays correctable in place.
 */
function StackedGroupCard({
  group,
  members,
  seriesById,
}: {
  group: SeriesGroupResource;
  members: SeriesResource[];
  seriesById: Map<number, SeriesResource>;
}) {
  const navigate = useNavigate();

  // Newest run (max start year); its id is the navigation + cover target even
  // when it is not yet resolved in the flat cache.
  const newest = [...group.series].sort(
    (a, b) => (b.start_year ?? -Infinity) - (a.start_year ?? -Infinity),
  )[0];
  const resolvedNewest = newest ? seriesById.get(newest.id) : undefined;
  // Publisher/tint from the newest resolved member, else any resolved member.
  const resolvedAny = resolvedNewest ?? members[0];
  const publisher = resolvedAny?.publisher ?? null;

  const years = group.series
    .map((m) => m.start_year)
    .filter((y): y is number => y != null);
  const yearRange =
    years.length > 0
      ? years.length === 1 || Math.min(...years) === Math.max(...years)
        ? `${years[0]}`
        : `${Math.min(...years)}–${Math.max(...years)}`
      : '';
  const groupSubline = yearRange
    ? `${group.series_count} volumes · ${yearRange}`
    : `${group.series_count} volumes`;
  const monitored = group.series.some((m) => m.monitored);
  const title = resolvedNewest?.title ?? group.title;

  const openNewest = () => {
    if (newest) navigate(`/series/${newest.id}`);
  };

  return (
    <div
      className={`${styles.card} ${styles.stackCard}`}
      data-testid="franchise-group"
      role="link"
      tabIndex={0}
      onClick={openNewest}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          openNewest();
        }
      }}
    >
      <div className={styles.coverRegion}>
        <Poster
          initial={group.title.charAt(0)}
          src={newest ? coverUrl(newest.id) : null}
          alt={`${title} cover`}
          tint={publisherTint(publisher)}
          overlay
          frameClassName={styles.posterFrame}
          fallbackClassName={styles.posterFallback}
          lazy
        />
        <CoverChrome
          monitored={monitored}
          topRight={
            <>
              {publisher && <Chip tone="overlay">{publisher}</Chip>}
              <Chip tone="accent">
                <LayersIcon size={10} /> {group.series_count} vols
              </Chip>
            </>
          }
        />
      </div>
      <ProgressStrip
        have={group.owned_count}
        total={group.issue_count}
        monitored={monitored}
        variant="strip"
      />
      <div className={styles.cardFooter}>
        <div className={styles.stackTitleRow}>
          <span className={styles.cardTitle} title={group.title}>
            {group.title}
          </span>
          <FranchiseMenuButton group={group} members={members} />
        </div>
        <span className={styles.cardSubline}>{groupSubline}</span>
      </div>
    </div>
  );
}

/* --- grouped row/table: collapsible franchise header ----------------------- */

/**
 * A multi-run franchise in a row/table context (FRG-UI-021): a collapsible
 * header carrying the group title, a roll-up progress strip, the run count, and
 * the ⋯ affordance, with the member runs nested beneath as rows.
 */
function FranchiseGroup({
  group,
  members,
  allMembers,
}: {
  group: SeriesGroupResource;
  members: SeriesResource[];
  allMembers: SeriesResource[];
}) {
  const [expanded, setExpanded] = useState(true);
  return (
    <section className={styles.franchise} data-testid="franchise-group">
      <div className={styles.franchiseHeader} data-testid="franchise-group-header">
        <button
          type="button"
          className={styles.collapseButton}
          aria-expanded={expanded}
          aria-label={expanded ? 'Collapse franchise' : 'Expand franchise'}
          data-testid="franchise-collapse"
          onClick={() => setExpanded((v) => !v)}
        >
          <span className={styles.chevron} data-collapsed={!expanded} aria-hidden>
            ▸
          </span>
          <span className={styles.franchiseTitle}>{group.title}</span>
        </button>
        <span className={styles.franchiseStats}>
          <ProgressStrip
            have={group.owned_count}
            total={group.issue_count}
            monitored
            variant="mini"
            className={styles.franchiseRollup}
          />
          <span className={styles.runCount}>{group.series_count} runs</span>
        </span>
        <FranchiseMenuButton group={group} members={allMembers} />
      </div>
      {expanded && (
        <div className={styles.franchiseMembers} data-testid="franchise-members">
          {members.map((s) => (
            <MemberRow key={s.id} series={s} />
          ))}
        </div>
      )}
    </section>
  );
}

/** A slim run row used under a franchise header and for single-run groups. */
function MemberRow({ series }: { series: SeriesResource }) {
  const { statistics: stats } = series;
  const cont = statusLabel(series) === 'Continuing';
  return (
    <Link
      to={`/series/${series.id}`}
      className={styles.memberRow}
      data-testid="series-row"
    >
      <span className={styles.rowMonitor} data-monitored={series.monitored}>
        <BookmarkIcon filled={series.monitored} size={13} />
      </span>
      <span className={styles.memberTitle} title={series.title}>
        {series.title}
      </span>
      <BookTypeBadge booktype={series.booktype} />
      <span className={styles.memberPublisher}>{series.publisher ?? '—'}</span>
      <ProgressStrip
        have={stats.file_count}
        total={stats.issue_count}
        monitored={series.monitored}
        variant="mini"
        className={styles.memberBar}
      />
      <span className={cont ? styles.statusContinuing : styles.statusEnded}>
        {statusLabel(series)}
      </span>
      <span className={styles.memberYear}>{series.start_year ?? '—'}</span>
    </Link>
  );
}

/* --- grouped body ---------------------------------------------------------- */

interface Franchise {
  group: SeriesGroupResource;
  members: SeriesResource[];
  allMembers: SeriesResource[];
  multiRun: boolean;
}

function useFranchises(
  groups: SeriesGroupResource[],
  seriesById: Map<number, SeriesResource>,
  needle: string,
  collectedFilter: LibraryCollectedFilter,
  statusFilter: LibraryStatusFilter,
): Franchise[] {
  return useMemo(() => {
    const filtering =
      needle.length > 0 || collectedFilter !== 'all' || statusFilter !== 'all';
    return groups
      .map((group): Franchise => {
        const allMembers = group.series
          .map((m) => seriesById.get(m.id))
          .filter((s): s is SeriesResource => s !== undefined)
          .sort((a, b) => a.sort_title.localeCompare(b.sort_title));
        const members = allMembers.filter(
          (s) =>
            matchesText(s, needle) &&
            matchesCollected(s, collectedFilter) &&
            matchesStatus(s, statusFilter),
        );
        // Multi-run is AUTHORITATIVE from the projection, not the count of
        // members cached in the flat index right now.
        const multiRun = group.kind === 'group' || group.series_count > 1;
        return { group, members, allMembers, multiRun };
      })
      // Keep a multi-run franchise (header/stack stand on the projection) unless
      // a filter is active and no member matches; drop a single-run franchise
      // whose sole run has not resolved or does not match.
      .filter((f) => (f.multiRun && !filtering ? true : f.members.length > 0))
      .sort((a, b) => a.group.title.localeCompare(b.group.title));
  }, [groups, seriesById, needle, collectedFilter, statusFilter]);
}

function GroupedBody({
  franchises,
  seriesById,
  viewMode,
  posterSize,
}: {
  franchises: Franchise[];
  seriesById: Map<number, SeriesResource>;
  viewMode: LibraryViewMode;
  posterSize: LibraryPosterSize;
}) {
  if (viewMode === 'poster') {
    return (
      <div
        className={styles.grid}
        data-testid="library-poster-grid"
        style={{
          gridTemplateColumns: `repeat(auto-fill, minmax(${POSTER_SIZE_PX[posterSize]}px, 1fr))`,
        }}
      >
        {franchises.map((f) =>
          f.multiRun ? (
            <StackedGroupCard
              key={f.group.id ?? `run-${f.members[0].id}`}
              group={f.group}
              members={f.allMembers}
              seriesById={seriesById}
            />
          ) : (
            <PosterCard key={`single-${f.members[0].id}`} series={f.members[0]} />
          ),
        )}
      </div>
    );
  }
  // Overview + Table share the row/header treatment (spec: "row/table contexts").
  return (
    <div className={styles.groupList} data-testid="library-grouped">
      {franchises.map((f) =>
        f.multiRun ? (
          <FranchiseGroup
            key={f.group.id ?? `run-${f.members[0].id}`}
            group={f.group}
            members={f.members}
            allMembers={f.allMembers}
          />
        ) : (
          <MemberRow key={`single-${f.members[0].id}`} series={f.members[0]} />
        ),
      )}
    </div>
  );
}

/* --- toolbar menu option rows ---------------------------------------------- */

function CheckRow({
  label,
  active,
  count,
  onClick,
  testId,
}: {
  label: string;
  active: boolean;
  count?: number;
  onClick: () => void;
  testId?: string;
}) {
  return (
    <button
      type="button"
      className={styles.optionRow}
      data-menuitem
      data-active={active}
      data-testid={testId}
      onClick={onClick}
    >
      <span className={styles.optionCheck} aria-hidden data-active={active}>
        <CheckIcon size={12} />
      </span>
      <span className={styles.optionLabel}>{label}</span>
      {count !== undefined && <span className={styles.optionCount}>{count}</span>}
    </button>
  );
}

/* --- screen ---------------------------------------------------------------- */

export function LibraryIndex() {
  const navigate = useNavigate();
  const { data, isLoading, isError } = useSeriesIndex();

  const viewMode = useUiStore((s) => s.libraryViewMode);
  const setViewMode = useUiStore((s) => s.setLibraryViewMode);
  const posterSize = useUiStore((s) => s.libraryPosterSize);
  const setPosterSize = useUiStore((s) => s.setLibraryPosterSize);
  const sortKey = useUiStore((s) => s.librarySortKey);
  const setSortKey = useUiStore((s) => s.setLibrarySortKey);
  const statusFilter = useUiStore((s) => s.libraryStatusFilter);
  const setStatusFilter = useUiStore((s) => s.setLibraryStatusFilter);
  const groupByFranchise = useUiStore((s) => s.libraryGroupByFranchise);
  const setGroupByFranchise = useUiStore((s) => s.setLibraryGroupByFranchise);
  const collectedFilter = useUiStore((s) => s.libraryCollectedFilter);
  const setCollectedFilter = useUiStore((s) => s.setLibraryCollectedFilter);

  const [filter, setFilter] = useState('');
  // One raised menu open at a time; a content-region click closes it.
  const [openMenu, setOpenMenu] = useState<'options' | 'sort' | 'filter' | null>(null);

  const groupsQuery = useSeriesGroups(groupByFranchise);
  const seriesById = useMemo(() => {
    const map = new Map<number, SeriesResource>();
    for (const s of data ?? []) map.set(s.id, s);
    return map;
  }, [data]);

  const needle = filter.trim().toLowerCase();

  const visible = useMemo(() => {
    const records = data ?? [];
    const filtered = records.filter(
      (s) =>
        matchesText(s, needle) &&
        matchesCollected(s, collectedFilter) &&
        matchesStatus(s, statusFilter),
    );
    return sortSeries(filtered, sortKey);
  }, [data, needle, sortKey, collectedFilter, statusFilter]);

  const franchises = useFranchises(
    groupsQuery.data ?? [],
    seriesById,
    needle,
    collectedFilter,
    statusFilter,
  );

  // Library-wide count line (independent of the active filters).
  const counts = useMemo(() => {
    const records = data ?? [];
    return {
      total: records.length,
      monitored: records.filter((s) => s.monitored).length,
      missing: records.filter((s) => s.statistics.missing_count > 0).length,
    };
  }, [data]);

  // Live per-option counts for the Filter menu. Status counts respect the text +
  // collected context; edition counts respect the text + status context.
  const filterCounts = useMemo(() => {
    const records = data ?? [];
    const statusPool = records.filter(
      (s) => matchesText(s, needle) && matchesCollected(s, collectedFilter),
    );
    const editionPool = records.filter(
      (s) => matchesText(s, needle) && matchesStatus(s, statusFilter),
    );
    return {
      status: {
        all: statusPool.length,
        monitored: statusPool.filter((s) => s.monitored).length,
        missing: statusPool.filter((s) => s.statistics.missing_count > 0).length,
        continuing: statusPool.filter((s) => s.status === 'continuing').length,
      },
      edition: {
        all: editionPool.length,
        collected: editionPool.filter((s) => s.booktype !== null).length,
        singles: editionPool.filter((s) => s.booktype === null).length,
      },
    };
  }, [data, needle, collectedFilter, statusFilter]);

  const viewButtons: { mode: LibraryViewMode; label: string; icon: ReactNode }[] = [
    { mode: 'poster', label: 'Posters', icon: <GridIcon size={16} /> },
    { mode: 'overview', label: 'Overview', icon: <RowsIcon size={16} /> },
    { mode: 'table', label: 'Table', icon: <TableIcon size={16} /> },
  ];

  const empty = data && data.length === 0;
  // "No match" only once we actually have something to match against — never
  // while the grouping projection is still loading (that shows its own note).
  const noMatch =
    data &&
    data.length > 0 &&
    (groupByFranchise
      ? !groupsQuery.isLoading && !groupsQuery.isError && franchises.length === 0
      : visible.length === 0);

  return (
    <>
      <Toolbar
        title="Library"
        actions={
          <span className={styles.toolbarControls}>
            <div className={styles.leftActions}>
              <ToolbarButton
                icon={<PlusIcon />}
                label="Add New"
                title="Add a new series"
                onClick={() => navigate('/add')}
              />
              <ToolbarButton
                icon={<ImportIcon />}
                label="Import"
                title="Import an existing library"
                onClick={() => navigate('/library-import')}
              />
              {/* Update All / RSS Sync arrive with their features (manual
                  refresh + RSS) — omitted until those ship. */}
            </div>
            <span className={styles.rightActions}>
              <input
                type="search"
                className={styles.filterInput}
                placeholder="Filter series"
                aria-label="Filter series"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              />
              <div className={styles.viewSwitcher} role="group" aria-label="View mode">
                {viewButtons.map((v) => (
                  <button
                    key={v.mode}
                    type="button"
                    className={styles.viewButton}
                    data-active={viewMode === v.mode}
                    aria-label={v.label}
                    aria-pressed={viewMode === v.mode}
                    title={v.label}
                    onClick={() => setViewMode(v.mode)}
                  >
                    {v.icon}
                  </button>
                ))}
              </div>

              <Menu
                open={openMenu === 'options'}
                onOpenChange={(o) => setOpenMenu(o ? 'options' : null)}
                label="Options"
                icon={<SlidersIcon size={16} />}
                testId="options-menu-trigger"
                menuTestId="options-menu"
              >
                <div className={styles.sectionLabel}>POSTER SIZE</div>
                <SegmentedControl
                  ariaLabel="Poster size"
                  value={posterSize}
                  onChange={setPosterSize}
                  options={[
                    { value: 's', label: 'S', testId: 'poster-size-s' },
                    { value: 'm', label: 'M', testId: 'poster-size-m' },
                    { value: 'l', label: 'L', testId: 'poster-size-l' },
                  ]}
                />
                <div className={styles.menuDivider} />
                <div className={styles.groupToggleRow}>
                  <div className={styles.groupToggleText}>
                    <div className={styles.groupToggleTitle}>Group volumes</div>
                    <div className={styles.groupToggleHint}>
                      Collapse a series' volumes into one entry
                    </div>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={groupByFranchise}
                    aria-label="Group volumes"
                    data-testid="group-by-toggle"
                    className={styles.switch}
                    data-on={groupByFranchise}
                    onClick={() => setGroupByFranchise(!groupByFranchise)}
                  >
                    <span className={styles.switchKnob} aria-hidden />
                  </button>
                </div>
              </Menu>

              <Menu
                open={openMenu === 'sort'}
                onOpenChange={(o) => setOpenMenu(o ? 'sort' : null)}
                label="Sort"
                icon={<SortIcon size={16} />}
                testId="sort-menu-trigger"
                menuTestId="sort-menu"
              >
                <CheckRow
                  label="Title"
                  active={sortKey === 'title'}
                  onClick={() => setSortKey('title')}
                  testId="sort-title"
                />
                <CheckRow
                  label="Publisher"
                  active={sortKey === 'publisher'}
                  onClick={() => setSortKey('publisher')}
                  testId="sort-publisher"
                />
                <CheckRow
                  label="Issues owned"
                  active={sortKey === 'issues'}
                  onClick={() => setSortKey('issues')}
                  testId="sort-issues"
                />
                <CheckRow
                  label="Year"
                  active={sortKey === 'year'}
                  onClick={() => setSortKey('year')}
                  testId="sort-year"
                />
              </Menu>

              <Menu
                open={openMenu === 'filter'}
                onOpenChange={(o) => setOpenMenu(o ? 'filter' : null)}
                label="Filter"
                icon={<FilterIcon size={16} />}
                testId="filter-menu-trigger"
                menuTestId="filter-menu"
              >
                <CheckRow
                  label="All"
                  active={statusFilter === 'all'}
                  count={filterCounts.status.all}
                  onClick={() => setStatusFilter('all')}
                  testId="status-filter-all"
                />
                <CheckRow
                  label="Monitored"
                  active={statusFilter === 'monitored'}
                  count={filterCounts.status.monitored}
                  onClick={() => setStatusFilter('monitored')}
                  testId="status-filter-monitored"
                />
                <CheckRow
                  label="Missing issues"
                  active={statusFilter === 'missing'}
                  count={filterCounts.status.missing}
                  onClick={() => setStatusFilter('missing')}
                  testId="status-filter-missing"
                />
                <CheckRow
                  label="Continuing"
                  active={statusFilter === 'continuing'}
                  count={filterCounts.status.continuing}
                  onClick={() => setStatusFilter('continuing')}
                  testId="status-filter-continuing"
                />
                <div className={styles.menuDivider} />
                <div className={styles.sectionLabel}>EDITIONS</div>
                <CheckRow
                  label="All editions"
                  active={collectedFilter === 'all'}
                  count={filterCounts.edition.all}
                  onClick={() => setCollectedFilter('all')}
                  testId="edition-filter-all"
                />
                <CheckRow
                  label="Collected only"
                  active={collectedFilter === 'collected'}
                  count={filterCounts.edition.collected}
                  onClick={() => setCollectedFilter('collected')}
                  testId="edition-filter-collected"
                />
                <CheckRow
                  label="Single issues only"
                  active={collectedFilter === 'singles'}
                  count={filterCounts.edition.singles}
                  onClick={() => setCollectedFilter('singles')}
                  testId="edition-filter-singles"
                />
              </Menu>
            </span>
          </span>
        }
      />
      <div className={styles.content} onClick={() => setOpenMenu(null)}>
        {isLoading && <p className={styles.stateNote}>Loading library…</p>}
        {isError && <p className={styles.stateNote}>Could not load the library.</p>}
        {empty && (
          <p className={styles.stateNote}>
            The library is empty. <Link to="/add">Add your first series</Link>.
          </p>
        )}
        {data && data.length > 0 && (
          <>
            <div className={styles.countLine} data-testid="library-count-line">
              <span className={styles.countTotal}>{counts.total} comics</span>
              <span className={styles.countDot}>·</span>
              <span className={styles.countMonitored}>{counts.monitored} monitored</span>
              <span className={styles.countDot}>·</span>
              <span className={styles.countMissing}>
                {counts.missing} with missing issues
              </span>
            </div>

            {noMatch ? (
              <div className={styles.noMatch}>
                <BookOpenIcon size={34} />
                <div className={styles.noMatchText}>No comics match your search.</div>
              </div>
            ) : groupByFranchise ? (
              groupsQuery.isLoading ? (
                <p className={styles.stateNote}>Loading franchises…</p>
              ) : groupsQuery.isError ? (
                <p className={styles.stateNote}>Could not load franchise groups.</p>
              ) : (
                <GroupedBody
                  franchises={franchises}
                  seriesById={seriesById}
                  viewMode={viewMode}
                  posterSize={posterSize}
                />
              )
            ) : viewMode === 'poster' ? (
              <div
                className={styles.grid}
                data-testid="library-poster-grid"
                style={{
                  gridTemplateColumns: `repeat(auto-fill, minmax(${POSTER_SIZE_PX[posterSize]}px, 1fr))`,
                }}
              >
                {visible.map((s) => (
                  <PosterCard key={s.id} series={s} />
                ))}
              </div>
            ) : viewMode === 'overview' ? (
              <div className={styles.overviewList} data-testid="library-overview">
                {visible.map((s) => (
                  <OverviewRow key={s.id} series={s} />
                ))}
              </div>
            ) : (
              <SeriesTable>
                {visible.map((s) => (
                  <SeriesTableRow key={s.id} series={s} />
                ))}
              </SeriesTable>
            )}
          </>
        )}
      </div>
    </>
  );
}
