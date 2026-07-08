import { create } from 'zustand';

/*
 * Local UI state (FRG-UI-001): view preferences that are NOT server data and must
 * never live in React Query. Zustand chosen over Context here because these values
 * are read by leaf toolbar/content components far from any provider and change
 * often (a re-render-scoped selector store fits better than context fan-out).
 */
export type LibraryViewMode = 'poster' | 'table';
export type LibrarySortKey = 'title' | 'added';
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
  librarySortKey: LibrarySortKey;
  setLibrarySortKey: (key: LibrarySortKey) => void;
  /**
   * Grouped-library toggle (FRG-UI-021): an ORTHOGONAL boolean over the
   * poster/table view mode — when on, the index nests successive runs of one
   * title under a collapsible franchise header instead of a flat list. Kept
   * separate from `libraryViewMode` (not a 4th mode) so the two preferences
   * compose independently.
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

export const useUiStore = create<UiState>((set) => ({
  libraryViewMode: 'poster',
  setLibraryViewMode: (libraryViewMode) => set({ libraryViewMode }),
  librarySortKey: 'title',
  setLibrarySortKey: (librarySortKey) => set({ librarySortKey }),
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
}));
