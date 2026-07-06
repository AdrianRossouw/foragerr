import { useMemo, useState, type KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSeriesIndex } from '../api/hooks';
import { matchSeries } from '../lib/fuzzyMatch';
import { SearchIcon } from './icons';
import type { AddSeriesNavigationState } from '../screens/add/AddSeries';
import styles from './HeaderQuickSearch.module.css';

/**
 * Global header quick-search (FRG-UI-019): fuzzy-matches the LOCAL library's
 * series titles AND aliases already cached under the `['series']` query
 * (`useSeriesIndex`) — no network request per keystroke, matching runs
 * entirely over data already in memory. Keyboard-navigable (arrows/Enter/
 * Escape); selecting a matched series navigates to its detail route. The
 * final row is always "Search ComicVine for '<term>'…", present even when
 * local matches exist, bridging a local-library miss to a remote add
 * (FRG-UI-005) by carrying the term via router navigation state.
 */

const MAX_RESULTS = 8;

interface SeriesRow {
  kind: 'series';
  id: number;
  title: string;
}

interface FallThroughRow {
  kind: 'fallthrough';
}

type ResultRow = SeriesRow | FallThroughRow;

export function HeaderQuickSearch() {
  const navigate = useNavigate();
  const seriesIndex = useSeriesIndex();
  const [term, setTerm] = useState('');
  const [dismissed, setDismissed] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);

  const trimmed = term.trim();
  const open = trimmed.length > 0 && !dismissed;

  // Empty/loading cache degrades to just the fall-through row rather than
  // erroring or showing a spinner masquerading as results (FRG-UI-019).
  const rows: ResultRow[] = useMemo(() => {
    if (!open) return [];
    const matches = seriesIndex.data ? matchSeries(trimmed, seriesIndex.data) : [];
    const seriesRows: SeriesRow[] = matches.slice(0, MAX_RESULTS).map((m) => ({
      kind: 'series',
      id: m.series.id,
      title: m.series.title,
    }));
    return [...seriesRows, { kind: 'fallthrough' }];
  }, [open, trimmed, seriesIndex.data]);

  function reset() {
    setTerm('');
    setDismissed(false);
    setActiveIndex(0);
  }

  function select(row: ResultRow) {
    if (row.kind === 'series') {
      navigate(`/series/${row.id}`);
    } else {
      const state: AddSeriesNavigationState = { prefillTerm: trimmed };
      navigate('/add', { state });
    }
    reset();
  }

  function onChange(value: string) {
    setTerm(value);
    setDismissed(false);
    setActiveIndex(0);
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (!open) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, rows.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const row = rows[activeIndex];
      if (row) select(row);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      setDismissed(true);
    }
  }

  return (
    <div className={styles.wrapper}>
      <span className={styles.icon} aria-hidden>
        <SearchIcon size={16} />
      </span>
      <input
        type="search"
        aria-label="Quick search your library"
        placeholder="Jump to a series, or search ComicVine…"
        className={styles.input}
        value={term}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
      />
      {open && (
        <ul className={styles.results} role="listbox" aria-label="Quick search results">
          {rows.map((row, index) => {
            const active = index === activeIndex;
            const key = row.kind === 'series' ? `series-${row.id}` : 'fallthrough';
            const label =
              row.kind === 'series' ? row.title : `Search ComicVine for “${trimmed}”…`;
            return (
              <li key={key}>
                <button
                  type="button"
                  role="option"
                  aria-selected={active}
                  className={active ? `${styles.result} ${styles.resultActive}` : styles.result}
                  data-testid={
                    row.kind === 'series' ? `quick-result-${row.id}` : 'quick-result-fallthrough'
                  }
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => select(row)}
                >
                  {label}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
