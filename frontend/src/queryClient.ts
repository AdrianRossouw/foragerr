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
    },
  });
}
