import { describe, it, expect } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../test/renderWithProviders';
import { createQueryClient } from '../queryClient';
import type { Fetcher } from '../api/fetcher';
import type { StoreSourceResource } from '../api/types';
import { GlobalBanner } from './GlobalBanner';

function fetcher(sources: StoreSourceResource[]): Fetcher {
  const resolve = async (path: string): Promise<unknown> => {
    if (path === '/api/v1/sources') return sources;
    throw new Error(`unexpected path ${path}`);
  };
  return resolve as unknown as Fetcher;
}

function src(state: StoreSourceResource['connection_state']): StoreSourceResource {
  return {
    id: 3,
    type: 'humble',
    name: 'Humble Bundle',
    connection_state: state,
    auto_sync: false,
    last_sync_status: 'ok',
    settings: {},
  };
}

describe('FRG-UI-029: global store-session banner', () => {
  it('FRG-UI-029 — an expired source raises the banner with a Reconnect action', async () => {
    renderWithProviders(<GlobalBanner />, {
      client: createQueryClient(),
      fetcher: fetcher([src('expired')]),
    });
    const banner = await screen.findByTestId('global-store-banner');
    expect(banner).toHaveTextContent(/session expired/i);
    expect(within(banner).getByRole('button', { name: 'Reconnect' })).toBeInTheDocument();
  });

  it('FRG-UI-029 — no expiry means no banner', async () => {
    renderWithProviders(<GlobalBanner />, {
      client: createQueryClient(),
      fetcher: fetcher([src('connected')]),
    });
    await waitFor(() =>
      expect(screen.queryByTestId('global-store-banner')).toBeNull(),
    );
  });

  it('FRG-UI-029 — the banner can be dismissed', async () => {
    const user = userEvent.setup();
    renderWithProviders(<GlobalBanner />, {
      client: createQueryClient(),
      fetcher: fetcher([src('expired')]),
    });
    const banner = await screen.findByTestId('global-store-banner');
    await user.click(within(banner).getByLabelText('Dismiss'));
    expect(screen.queryByTestId('global-store-banner')).toBeNull();
  });
});
