import { create } from 'zustand';

/*
 * Local UI state (FRG-UI-001): view preferences that are NOT server data and must
 * never live in React Query. Zustand chosen over Context here because these values
 * are read by leaf toolbar/content components far from any provider and change
 * often (a re-render-scoped selector store fits better than context fan-out).
 */
export type LibraryViewMode = 'poster' | 'table';

interface UiState {
  libraryViewMode: LibraryViewMode;
  setLibraryViewMode: (mode: LibraryViewMode) => void;
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
}

export const useUiStore = create<UiState>((set) => ({
  libraryViewMode: 'poster',
  setLibraryViewMode: (libraryViewMode) => set({ libraryViewMode }),
  sidebarCollapsed: false,
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
}));
