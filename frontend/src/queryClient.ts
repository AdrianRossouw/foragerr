import { QueryClient } from '@tanstack/react-query';

/**
 * Shared React Query client factory (FRG-UI-001). All server state flows through a
 * client built here; tests construct their own instance so caches never leak
 * between cases.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Screens rely on the WebSocketBridge for freshness, not aggressive
        // polling; retries off keeps failing tests fast and honest.
        retry: false,
        refetchOnWindowFocus: false,
      },
      mutations: {
        // `always`, not the default `online`: a mutation started while the
        // browser reports itself offline would otherwise be PAUSED, and a paused
        // mutation's promise never settles. Every caller that awaits one — and
        // every optimistic value released in its `finally` — would be stranded
        // on a control that stays busy forever. Failing fast reaches the
        // revert-and-report path instead.
        networkMode: 'always',
      },
    },
  });
}
