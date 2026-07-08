import { useMemo, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { Toolbar } from '../../components/Toolbar';
import { ToolbarButton, ToolbarSeparator } from '../../components/ToolbarButton';
import { ProgressPill } from '../../components/ProgressPill';
import { Poster } from '../../components/Poster';
import {
  BookmarkIcon,
  FolderScanIcon,
  GridIcon,
  TableIcon,
} from '../../components/icons';
import {
  useSeriesGroups,
  useSeriesIndex,
  useUpdateSeriesGroup,
} from '../../api/hooks';
import { coverUrl } from '../../api/urls';
import { useUiStore, type LibrarySortKey } from '../../store/uiStore';
import { formatBytes } from '../../lib/format';
import type { SeriesGroupResource, SeriesResource } from '../../api/types';
import styles from './LibraryIndex.module.css';

/**
 * Library index (FRG-UI-003): Sonarr-shaped series index with poster/table
 * view toggle, toolbar sort + text filter, alphabet jump bar and a stats
 * footer. Posters come exclusively from the LOCAL cover cache endpoint —
 * never an external ComicVine host.
 */

function sortSeries(
  records: readonly SeriesResource[],
  sortKey: LibrarySortKey,
): SeriesResource[] {
  const sorted = [...records];
  if (sortKey === 'added') {
    // Newest additions first.
    sorted.sort((a, b) => b.added_at.localeCompare(a.added_at));
  } else {
    sorted.sort((a, b) => a.sort_title.localeCompare(b.sort_title));
  }
  return sorted;
}

function jumpLetter(series: SeriesResource): string {
  const first = series.sort_title.charAt(0).toUpperCase();
  return first >= 'A' && first <= 'Z' ? first : '#';
}

function PosterCard({ series }: { series: SeriesResource }) {
  const { statistics: stats } = series;
  return (
    <Link
      to={`/series/${series.id}`}
      className={styles.card}
      id={`series-card-${series.id}`}
      data-testid="series-card"
    >
      <Poster
        initial={series.title.charAt(0)}
        src={coverUrl(series.id)}
        alt={`${series.title} cover`}
        frameClassName={styles.posterFrame}
        fallbackClassName={styles.posterFallback}
        lazy
      />
      <div className={styles.cardFooter}>
        <span className={styles.cardTitle} title={series.title}>
          {series.title}
        </span>
        <span className={styles.cardMeta}>
          <span
            className={series.monitored ? styles.monitoredMark : styles.unmonitoredMark}
          >
            <BookmarkIcon filled={series.monitored} size={12} />
            {series.monitored ? 'Monitored' : 'Unmonitored'}
          </span>
          <ProgressPill
            have={stats.file_count}
            total={stats.issue_count}
            monitored={series.monitored}
          />
        </span>
      </div>
    </Link>
  );
}

function PosterGrid({ series }: { series: SeriesResource[] }) {
  const letters = useMemo(() => {
    const map = new Map<string, number>();
    for (const s of series) {
      const letter = jumpLetter(s);
      if (!map.has(letter)) map.set(letter, s.id);
    }
    return map;
  }, [series]);

  return (
    <div className={styles.gridWrap}>
      <div className={styles.grid} data-testid="library-poster-grid">
        {series.map((s) => (
          <PosterCard key={s.id} series={s} />
        ))}
      </div>
      <nav className={styles.jumpBar} aria-label="Jump to letter">
        {[...letters.entries()].map(([letter, firstId]) => (
          <button
            key={letter}
            type="button"
            className={styles.jumpLetter}
            onClick={() =>
              document
                .getElementById(`series-card-${firstId}`)
                ?.scrollIntoView?.({ block: 'start' })
            }
          >
            {letter}
          </button>
        ))}
      </nav>
    </div>
  );
}

function SeriesTable({ series }: { series: SeriesResource[] }) {
  return (
    <table className={styles.table} data-testid="library-table">
      <thead>
        <tr>
          <th className={styles.iconCol} aria-label="Monitored" />
          <th>Title</th>
          <th>Publisher</th>
          <th>Year</th>
          <th>Issues</th>
          <th>Size on Disk</th>
        </tr>
      </thead>
      <tbody>
        {series.map((s) => (
          <tr key={s.id} data-testid="series-row">
            <td className={styles.iconCol}>
              <span
                className={s.monitored ? styles.monitoredMark : styles.unmonitoredMark}
                aria-label={s.monitored ? 'Monitored' : 'Unmonitored'}
              >
                <BookmarkIcon filled={s.monitored} size={14} />
              </span>
            </td>
            <td>
              <Link className={styles.titleLink} to={`/series/${s.id}`}>
                {s.title}
              </Link>
            </td>
            <td>{s.publisher ?? '—'}</td>
            <td>{s.start_year ?? '—'}</td>
            <td>
              <ProgressPill
                have={s.statistics.file_count}
                total={s.statistics.issue_count}
                monitored={s.monitored}
              />
            </td>
            <td>{formatBytes(s.statistics.size_on_disk)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * Rename / reassign affordance (FRG-SER-017) anchored on a franchise header.
 * Rename targets the group any member belongs to (so it PUTs against a member
 * series id); detach reassigns one run out of the group. Both go through the
 * shared group-edit mutation, which refreshes the flat index + the grouping
 * projection on success.
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
    if (!trimmed) return;
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

/** One multi-run franchise: a collapsible header + its member poster cards. */
function FranchiseGroup({
  group,
  members,
}: {
  group: SeriesGroupResource;
  members: SeriesResource[];
}) {
  const [expanded, setExpanded] = useState(true);
  const [menuOpen, setMenuOpen] = useState(false);

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
          <ProgressPill have={group.owned_count} total={group.issue_count} monitored />
          <span className={styles.runCount}>{group.series_count} runs</span>
        </span>
        <div className={styles.franchiseMenuWrap}>
          <button
            type="button"
            className={styles.menuButton}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            aria-label="Franchise actions"
            data-testid="franchise-group-menu"
            onClick={() => setMenuOpen((v) => !v)}
          >
            ⋯
          </button>
          {menuOpen && (
            <FranchiseMenu
              group={group}
              members={members}
              onDone={() => setMenuOpen(false)}
            />
          )}
        </div>
      </div>
      {expanded && (
        <div className={styles.franchiseMembers} data-testid="franchise-members">
          {members.map((s) => (
            <PosterCard key={s.id} series={s} />
          ))}
        </div>
      )}
    </section>
  );
}

/**
 * Grouped library body (FRG-UI-021). Franchise metadata + roll-up stats come
 * from the groups projection; member runs are joined back to the full flat
 * `SeriesResource` (by id) so the existing `PosterCard` renders them with cover
 * + statistics unchanged. A single-run franchise renders as an ordinary card
 * with NO group chrome; a multi-run franchise nests its runs under a
 * collapsible header. The title filter is applied to members; a franchise with
 * no matching member drops out.
 */
function FranchiseGroupedView({
  groups,
  seriesById,
  filter,
}: {
  groups: SeriesGroupResource[];
  seriesById: Map<number, SeriesResource>;
  filter: string;
}) {
  const franchises = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return groups
      .map((group) => {
        const resolved = group.series
          .map((m) => seriesById.get(m.id))
          .filter((s): s is SeriesResource => s !== undefined);
        const members = resolved
          .filter((s) => (needle ? s.title.toLowerCase().includes(needle) : true))
          .sort((a, b) => a.sort_title.localeCompare(b.sort_title));
        return { group, members, multiRun: resolved.length > 1 };
      })
      .filter((f) => f.members.length > 0)
      .sort((a, b) => a.group.title.localeCompare(b.group.title));
  }, [groups, seriesById, filter]);

  if (franchises.length === 0) {
    return <p className={styles.stateNote}>No series match the current filter.</p>;
  }

  return (
    <div className={styles.groupList} data-testid="library-grouped">
      {franchises.map(({ group, members, multiRun }) =>
        multiRun ? (
          <FranchiseGroup
            key={group.id ?? `run-${members[0].id}`}
            group={group}
            members={members}
          />
        ) : (
          // Single-run franchise: an ordinary card, no franchise header chrome.
          <div key={`single-${members[0].id}`} className={styles.singleRun}>
            <PosterCard series={members[0]} />
          </div>
        ),
      )}
    </div>
  );
}

export function LibraryIndex() {
  const { data, isLoading, isError } = useSeriesIndex();
  const viewMode = useUiStore((s) => s.libraryViewMode);
  const setViewMode = useUiStore((s) => s.setLibraryViewMode);
  const sortKey = useUiStore((s) => s.librarySortKey);
  const setSortKey = useUiStore((s) => s.setLibrarySortKey);
  const groupByFranchise = useUiStore((s) => s.libraryGroupByFranchise);
  const toggleGroupByFranchise = useUiStore((s) => s.toggleLibraryGroupByFranchise);
  const [filter, setFilter] = useState('');

  // Grouping projection is fetched only while the toggle is on; the flat index
  // (already loaded) supplies each member's full resource for rendering.
  const groupsQuery = useSeriesGroups(groupByFranchise);
  const seriesById = useMemo(() => {
    const map = new Map<number, SeriesResource>();
    for (const s of data ?? []) map.set(s.id, s);
    return map;
  }, [data]);

  const visible = useMemo(() => {
    const records = data ?? [];
    const needle = filter.trim().toLowerCase();
    const filtered = needle
      ? records.filter((s) => s.title.toLowerCase().includes(needle))
      : records;
    return sortSeries(filtered, sortKey);
  }, [data, filter, sortKey]);

  const totals = useMemo(() => {
    const records = data ?? [];
    return {
      series: records.length,
      monitored: records.filter((s) => s.monitored).length,
      issues: records.reduce((n, s) => n + s.statistics.issue_count, 0),
      files: records.reduce((n, s) => n + s.statistics.file_count, 0),
      size: records.reduce((n, s) => n + s.statistics.size_on_disk, 0),
    };
  }, [data]);

  return (
    <>
      <Toolbar
        title="Library"
        actions={
          <span className={styles.toolbarControls}>
            <input
              type="search"
              className={styles.filterInput}
              placeholder="Filter series"
              aria-label="Filter series"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
            <select
              className={styles.sortSelect}
              aria-label="Sort"
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as LibrarySortKey)}
            >
              <option value="title">Sort: Title</option>
              <option value="added">Sort: Date Added</option>
            </select>
            <ToolbarSeparator />
            <ToolbarButton
              icon={<FolderScanIcon />}
              label="Group"
              title="Group by franchise"
              active={groupByFranchise}
              onClick={toggleGroupByFranchise}
              testId="group-by-toggle"
            />
            <ToolbarSeparator />
            <ToolbarButton
              icon={<GridIcon />}
              label="Posters"
              active={viewMode === 'poster'}
              onClick={() => setViewMode('poster')}
            />
            <ToolbarButton
              icon={<TableIcon />}
              label="Table"
              active={viewMode === 'table'}
              onClick={() => setViewMode('table')}
            />
          </span>
        }
      />
      <div className={styles.content}>
        {isLoading && <p className={styles.stateNote}>Loading library…</p>}
        {isError && <p className={styles.stateNote}>Could not load the library.</p>}
        {data && data.length === 0 && (
          <p className={styles.stateNote}>
            The library is empty. <Link to="/add">Add your first series</Link>.
          </p>
        )}
        {data && data.length > 0 && (
          <>
            {groupByFranchise ? (
              groupsQuery.isLoading ? (
                <p className={styles.stateNote}>Loading franchises…</p>
              ) : groupsQuery.isError ? (
                <p className={styles.stateNote}>Could not load franchise groups.</p>
              ) : (
                <FranchiseGroupedView
                  groups={groupsQuery.data ?? []}
                  seriesById={seriesById}
                  filter={filter}
                />
              )
            ) : viewMode === 'poster' ? (
              <PosterGrid series={visible} />
            ) : (
              <SeriesTable series={visible} />
            )}
            <footer className={styles.statsFooter}>
              <span>
                <strong>Series</strong> {totals.series}
              </span>
              <span>
                <strong>Monitored</strong> {totals.monitored}
              </span>
              <span>
                <strong>Issues</strong> {totals.issues}
              </span>
              <span>
                <strong>Files</strong> {totals.files}
              </span>
              <span>
                <strong>Total Size</strong> {formatBytes(totals.size)}
              </span>
            </footer>
          </>
        )}
      </div>
    </>
  );
}
