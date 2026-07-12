import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { App } from './App';
import { createQueryClient } from './queryClient';
import { FetcherProvider, defaultFetcher } from './api/fetcher';
import { AuthGate } from './auth/AuthGate';
// Self-hosted fonts + icons (FRG-UI-002): Roboto (300/400/500/700) and Font
// Awesome 6 Free are vendored from npm packages and bundled by Vite into the
// SPA's own assets — no Google Fonts / Font Awesome CDN request is ever made at
// runtime (SSRF/egress posture, offline tailnet operation).
// Latin subset only (the UI is English) — keeps the vendored font footprint
// proportionate per FRG-UI-002 design decision 2.
import '@fontsource/roboto/latin-300.css';
import '@fontsource/roboto/latin-400.css';
import '@fontsource/roboto/latin-500.css';
import '@fontsource/roboto/latin-700.css';
// 900 exists solely for the logo wordmark (handoff: Roboto 900) — without it
// the browser would synthesize the weight from 700.
import '@fontsource/roboto/latin-900.css';
// Roboto Mono 400 backs --font-family-mono (paths, API keys, log lines); the
// token named it from day one but the face was never vendored, so every user
// saw their platform's fallback mono instead. Regular weight only — all mono
// usage in the app is small unemphasized text.
import '@fontsource/roboto-mono/latin-400.css';
import '@fortawesome/fontawesome-free/css/fontawesome.min.css';
import '@fortawesome/fontawesome-free/css/solid.min.css';
import './theme/global.css';

const queryClient = createQueryClient();

const rootEl = document.getElementById('root');
if (!rootEl) throw new Error('Root element #root not found');

createRoot(rootEl).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <FetcherProvider fetcher={defaultFetcher}>
        <BrowserRouter>
          <AuthGate>
            <App />
          </AuthGate>
        </BrowserRouter>
      </FetcherProvider>
    </QueryClientProvider>
  </StrictMode>,
);
