import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Toolbar } from '../../components/Toolbar';
import { ToolbarButton, ToolbarSeparator } from '../../components/ToolbarButton';
import { ProgressPill } from '../../components/ProgressPill';
import { BookmarkIcon, GridIcon, TableIcon } from '../../components/icons';
import { useSeriesIndex } from '../../api/hooks';
import { useUiStore, type LibrarySortKey } from '../../store/uiStore';
import { formatBytes } from '../../lib/format';
import type { SeriesResource } from '../../api/types';
import styles from './LibraryIndex.module.css';

/**
 * Library index (FRG-UI-003): Sonarr-shaped series index with poster/table
 * view toggle, toolbar sort + text filter, alphabet jump bar and a stats
 * footer. Posters come exclusively from the LOCAL cover cache endpoint —
 * never an external ComicVine host.
 */

function coverUrl(id: number): string {
  return `/api/v1/series/${id}/cover`;
}

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
      <div className={styles.posterFrame}>
        <span className={styles.posterFallback} aria-hidden>
          {series.title.charAt(0)}
        </span>
        <img
          className={styles.poster}
          src={coverUrl(series.id)}
          alt={`${series.title} cover`}
          loading="lazy"
        />
      </div>
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

export function LibraryIndex() {
  const { data, isLoading, isError } = useSeriesIndex();
  const viewMode = useUiStore((s) => s.libraryViewMode);
  const setViewMode = useUiStore((s) => s.setLibraryViewMode);
  const sortKey = useUiStore((s) => s.librarySortKey);
  const setSortKey = useUiStore((s) => s.setLibrarySortKey);
  const [filter, setFilter] = useState('');

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
            {viewMode === 'poster' ? (
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
