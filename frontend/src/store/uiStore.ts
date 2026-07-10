import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

/*
 * Local UI state (FRG-UI-001): view preferences that are NOT server data and must
 * never live in React Query. Zustand chosen over Context here because these values
 * are read by leaf toolbar/content components far from any provider and change
 * often (a re-render-scoped selector store fits better than context fan-out).
 *
 * The library-view preferences (mode, poster size, sort, status filter, collected
 * filter) PERSIST across sessions (FRG-UI-003) via zustand's `persist` middleware.
 * Everything else in the store (sidebar collapse, the interactive-search launch
 * seam) is transient and deliberately left OUT of the persisted partition.
 */

/** Poster / Overview / Table (FRG-UI-003). */
export type LibraryViewMode = 'poster' | 'overview' | 'table';
/** Sort keys the toolbar's Sort menu offers (FRG-UI-003). */
export type LibrarySortKey = 'title' | 'publisher' | 'issues' | 'year';
/**
 * Status filter the toolbar's Filter menu offers (FRG-UI-003): `all` shows
 * everything, `monitored` only monitored series, `missing` only series with
 * missing issues, `continuing` only series whose status is continuing. A
 * display-only narrowing — it never touches per-series state.
 */
export type LibraryStatusFilter = 'all' | 'monitored' | 'missing' | 'continuing';
/** Poster card size (FRG-UI-003) — S/M/L in the Options menu. */
export type LibraryPosterSize = 's' | 'm' | 'l';
/**
 * Collected-editions filter (FRG-UI-022): a display-only partition of the
 * library by book-type (FRG-SER-018). `all` shows everything; `collected`
 * shows only typed (trade/GN/HC/one-shot) series; `singles` shows only
 * null-typed single-issues runs. It never touches any per-series state.
 */
export type LibraryCollectedFilter = 'all' | 'collected' | 'singles';

interface UiState {
  libraryViewMode: LibraryViewMode;
  setLibraryViewMode: (mode: LibraryViewMode) => void;
  libraryPosterSize: LibraryPosterSize;
  setLibraryPosterSize: (size: LibraryPosterSize) => void;
  librarySortKey: LibrarySortKey;
  setLibrarySortKey: (key: LibrarySortKey) => void;
  libraryStatusFilter: LibraryStatusFilter;
  setLibraryStatusFilter: (filter: LibraryStatusFilter) => void;
  /**
   * Grouped-library toggle (FRG-UI-021): an ORTHOGONAL boolean over the
   * poster/overview/table view mode — when on, the index folds successive runs
   * of one title into a stacked card (poster) or a collapsible franchise header
   * (overview/table) instead of a flat list. Kept separate from
   * `libraryViewMode` (not a 4th mode) so the two preferences compose
   * independently.
   */
  libraryGroupByFranchise: boolean;
  toggleLibraryGroupByFranchise: () => void;
  setLibraryGroupByFranchise: (on: boolean) => void;
  /** Collected-editions filter (FRG-UI-022) — display-only library partition. */
  libraryCollectedFilter: LibraryCollectedFilter;
  setLibraryCollectedFilter: (filter: LibraryCollectedFilter) => void;
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  /**
   * Interactive-search overlay target (FRG-UI-004 launch seam). Series detail
   * sets this from a row's search button; the FRG-UI-007 overlay renders
   * whenever it is non-null and clears it on close.
   */
  interactiveSearchIssueId: number | null;
  openInteractiveSearch: (issueId: number) => void;
  closeInteractiveSearch: () => void;
}

/* --- persisted-value allow-lists ------------------------------------------ */
// A persisted preference read back from an OLDER session may carry a value this
// build no longer accepts (e.g. a removed 'added' sort key). We validate each
// hydrated field against its allow-list and fall back to the default rather than
// let a stale value crash a render. Kept next to the store so the sets stay in
// sync with the union types above.
const VIEW_MODES: readonly LibraryViewMode[] = ['poster', 'overview', 'table'];
const SORT_KEYS: readonly LibrarySortKey[] = ['title', 'publisher', 'issues', 'year'];
const STATUS_FILTERS: readonly LibraryStatusFilter[] = [
  'all',
  'monitored',
  'missing',
  'continuing',
];
const POSTER_SIZES: readonly LibraryPosterSize[] = ['s', 'm', 'l'];
const COLLECTED_FILTERS: readonly LibraryCollectedFilter[] = [
  'all',
  'collected',
  'singles',
];

function oneOf<T>(allowed: readonly T[], value: unknown, fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback;
}

/** Default library-view preferences — the fallback for any invalid persisted value. */
const DEFAULTS = {
  libraryViewMode: 'poster' as LibraryViewMode,
  libraryPosterSize: 'm' as LibraryPosterSize,
  librarySortKey: 'title' as LibrarySortKey,
  libraryStatusFilter: 'all' as LibraryStatusFilter,
  libraryCollectedFilter: 'all' as LibraryCollectedFilter,
};

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      ...DEFAULTS,
      setLibraryViewMode: (libraryViewMode) => set({ libraryViewMode }),
      setLibraryPosterSize: (libraryPosterSize) => set({ libraryPosterSize }),
      setLibrarySortKey: (librarySortKey) => set({ librarySortKey }),
      setLibraryStatusFilter: (libraryStatusFilter) => set({ libraryStatusFilter }),
      libraryGroupByFranchise: false,
      toggleLibraryGroupByFranchise: () =>
        set((s) => ({ libraryGroupByFranchise: !s.libraryGroupByFranchise })),
      setLibraryGroupByFranchise: (libraryGroupByFranchise) =>
        set({ libraryGroupByFranchise }),
      libraryCollectedFilter: 'all',
      setLibraryCollectedFilter: (libraryCollectedFilter) =>
        set({ libraryCollectedFilter }),
      sidebarCollapsed: false,
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      interactiveSearchIssueId: null,
      openInteractiveSearch: (interactiveSearchIssueId) =>
        set({ interactiveSearchIssueId }),
      closeInteractiveSearch: () => set({ interactiveSearchIssueId: null }),
    }),
    {
      name: 'foragerr-library-view',
      storage: createJSONStorage(() => localStorage),
      // Persist EXACTLY the library-view preferences — nothing transient.
      partialize: (s) => ({
        libraryViewMode: s.libraryViewMode,
        libraryPosterSize: s.libraryPosterSize,
        librarySortKey: s.librarySortKey,
        libraryStatusFilter: s.libraryStatusFilter,
        libraryCollectedFilter: s.libraryCollectedFilter,
      }),
      // Sanitize every hydrated preference back to a valid value so a stale
      // session (an old sort key, a mode this build removed) can never crash.
      merge: (persisted, current) => {
        const p = (persisted ?? {}) as Partial<UiState>;
        return {
          ...current,
          libraryViewMode: oneOf(VIEW_MODES, p.libraryViewMode, DEFAULTS.libraryViewMode),
          libraryPosterSize: oneOf(
            POSTER_SIZES,
            p.libraryPosterSize,
            DEFAULTS.libraryPosterSize,
          ),
          librarySortKey: oneOf(SORT_KEYS, p.librarySortKey, DEFAULTS.librarySortKey),
          libraryStatusFilter: oneOf(
            STATUS_FILTERS,
            p.libraryStatusFilter,
            DEFAULTS.libraryStatusFilter,
          ),
          libraryCollectedFilter: oneOf(
            COLLECTED_FILTERS,
            p.libraryCollectedFilter,
            DEFAULTS.libraryCollectedFilter,
          ),
        };
      },
    },
  ),
);
