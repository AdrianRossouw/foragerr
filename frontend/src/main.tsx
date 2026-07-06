import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { App } from './App';
import { createQueryClient } from './queryClient';
import { FetcherProvider, defaultFetcher } from './api/fetcher';
import './theme/global.css';

const queryClient = createQueryClient();

const rootEl = document.getElementById('root');
if (!rootEl) throw new Error('Root element #root not found');

createRoot(rootEl).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <FetcherProvider fetcher={defaultFetcher}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </FetcherProvider>
    </QueryClientProvider>
  </StrictMode>,
);
