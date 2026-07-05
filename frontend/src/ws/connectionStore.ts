import { create } from 'zustand';

/*
 * Connection state (FRG-UI-001) — LOCAL UI state, not server data, so it lives in
 * the small client store (Zustand), never in React Query. The sidebar footer reads
 * `status` to render connected/disconnected.
 */
export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected';

interface ConnectionState {
  status: ConnectionStatus;
  setStatus: (status: ConnectionStatus) => void;
}

export const useConnectionStore = create<ConnectionState>((set) => ({
  status: 'connecting',
  setStatus: (status) => set({ status }),
}));
