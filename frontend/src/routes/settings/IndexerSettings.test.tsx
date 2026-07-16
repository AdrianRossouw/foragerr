import { describe, it, expect } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import { ApiRequestError, type FetcherInit } from '../../api/fetcher';
import {
  mockIndexers,
  mockIndexerSchemas,
} from '../../test/providerMocks';
import type { ProviderResource } from '../../components/settings/providerTypes';
import { IndexerSettings } from './IndexerSettings';

/*
 * FRG-UI-008 — indexer settings screen: provider cards with enable toggles,
 * the add/edit modal rendered ENTIRELY from GET /indexer/schema, write-only
 * secrets, and the Test button surfacing field-precise pass/fail from
 * POST /indexer/test. All server traffic is the injected fake fetcher.
 */

function indexerResolver(overrides?: {
  rows?: () => ProviderResource[];
  onTest?: (init?: FetcherInit) => unknown;
  onSave?: (path: string, init?: FetcherInit) => unknown;
}) {
  return (path: string, init?: FetcherInit): unknown => {
    if (path === '/api/v1/indexer/schema') return mockIndexerSchemas;
    if (path === '/api/v1/indexer/test') {
      if (overrides?.onTest) return overrides.onTest(init);
      return {
        success: true,
        message: 'indexer reachable; capabilities retrieved',
        categories: { 7030: 'Books/Comics' },
        degraded: false,
      };
    }
    if (init?.method === 'POST' || init?.method === 'PUT') {
      if (overrides?.onSave) return overrides.onSave(path, init);
      return { ...mockIndexers[0], ...(init.body as object) };
    }
    if (path === '/api/v1/indexer') {
      return overrides?.rows ? overrides.rows() : mockIndexers;
    }
    throw new Error(`unexpected path: ${path}`);
  };
}

describe('FRG-UI-008: indexer settings cards', () => {
  it('FRG-UI-008 — configured indexers render as cards with an enable toggle reflecting the enabled flag', async () => {
    const { fetcher } = fakeFetcher(indexerResolver());
    renderWithProviders(<IndexerSettings />, { fetcher });

    const card = await screen.findByTestId('provider-card-1');
    expect(within(card).getByText('DogNZB')).toBeInTheDocument();
    expect(within(card).getByRole('switch')).toHaveAttribute('aria-checked', 'true');
    expect(within(card).getByText('RSS')).toBeInTheDocument();
    expect(within(card).getByText('Automatic Search')).toBeInTheDocument();
    expect(within(card).getByText('Interactive Search')).toBeInTheDocument();
  });

  it('FRG-UI-038 — the card wrapper is not interactive, yet the "Edit" button is keyboard-reachable and opens the modal', async () => {
    const user = userEvent.setup();
    const { fetcher } = fakeFetcher(indexerResolver());
    renderWithProviders(<IndexerSettings />, { fetcher });

    const card = await screen.findByTestId('provider-card-1');
    // The card wrapper must NOT be an interactive control — otherwise the
    // enable switch inside it is a nested interactive (axe nested-interactive).
    expect(card).not.toHaveAttribute('role', 'button');
    expect(card).not.toHaveAttribute('tabindex');

    // The keyboard/AT edit affordance is a real button named "Edit <name>"; it
    // is focusable and opens the edit dialog.
    const editButton = within(card).getByRole('button', { name: 'Edit DogNZB' });
    editButton.focus();
    expect(editButton).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(
      screen.getByRole('dialog', { name: 'Edit Indexer — Newznab' }),
    ).toBeInTheDocument();

    // The enable switch remains a sibling control, not nested in a button.
    expect(within(card).getByRole('switch')).toBeInTheDocument();
  });

  it('FRG-UI-008 — a disabled indexer\'s card reflects the disabled state', async () => {
    const disabled = [{ ...mockIndexers[0], enabled: false }];
    const { fetcher } = fakeFetcher(indexerResolver({ rows: () => disabled }));
    renderWithProviders(<IndexerSettings />, { fetcher });

    const card = await screen.findByTestId('provider-card-1');
    expect(within(card).getByRole('switch')).toHaveAttribute('aria-checked', 'false');
    expect(within(card).getByText('Disabled')).toBeInTheDocument();
  });

  it('FRG-UI-008 — the card enable toggle issues a partial PUT and refetches the provider list', async () => {
    const user = userEvent.setup();
    const { spy, fetcher } = fakeFetcher(indexerResolver());
    renderWithProviders(<IndexerSettings />, { fetcher });

    const card = await screen.findByTestId('provider-card-1');
    await user.click(within(card).getByRole('switch'));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('/api/v1/indexer/1', {
        method: 'PUT',
        body: { enabled: false },
      }),
    );
    // invalidation → the ['indexer'] list is refetched
    await waitFor(() =>
      expect(
        spy.mock.calls.filter(([p, i]) => p === '/api/v1/indexer' && !i).length,
      ).toBeGreaterThan(1),
    );
  });
});

describe('FRG-UI-008: schema-driven add/edit modal', () => {
  it('FRG-UI-008 — the edit modal renders every widget from schema field metadata, secrets write-only', async () => {
    const user = userEvent.setup();
    const { fetcher } = fakeFetcher(indexerResolver());
    renderWithProviders(<IndexerSettings />, { fetcher });

    await user.click(await screen.findByTestId('provider-card-1'));
    const dialog = screen.getByRole('dialog', {
      name: 'Edit Indexer — Newznab',
    });

    // Row fields and schema fields all render through the ONE renderer.
    expect(within(dialog).getByLabelText('Name')).toHaveValue('DogNZB');
    expect(within(dialog).getByLabelText('Enable RSS')).toBeChecked();
    expect(within(dialog).getByLabelText('URL')).toHaveValue('https://api.dognzb.cr');
    expect(within(dialog).getByLabelText('Categories').tagName).toBe('SELECT');

    // Secret field: write-only — empty input, "set" placeholder, no stored value.
    const apiKey = within(dialog).getByLabelText('API Key') as HTMLInputElement;
    expect(apiKey).toHaveAttribute('type', 'password');
    expect(apiKey.value).toBe('');
    expect(apiKey).toHaveAttribute('placeholder', '••••••••');
    expect(
      within(dialog).getByTestId('secret-hint-api_key'),
    ).toHaveTextContent('leave blank to keep');

    // Advanced fields stay hidden until the toolbar Show Advanced toggle.
    expect(
      within(dialog).queryByLabelText('Additional Parameters'),
    ).not.toBeInTheDocument();
  });

  it('FRG-UI-008 — Show Advanced reveals advanced schema and row fields in the modal', async () => {
    const user = userEvent.setup();
    const { fetcher } = fakeFetcher(indexerResolver());
    renderWithProviders(<IndexerSettings />, { fetcher });

    await user.click(
      await screen.findByRole('button', { name: 'Show Advanced' }),
    );
    await user.click(screen.getByTestId('provider-card-1'));
    const dialog = screen.getByRole('dialog', { name: 'Edit Indexer — Newznab' });

    expect(within(dialog).getByLabelText('Additional Parameters')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('Indexer Priority')).toHaveValue(25);
  });

  it('FRG-UI-008 — Test failure is surfaced against the specific field it concerns', async () => {
    const user = userEvent.setup();
    const { fetcher } = fakeFetcher(
      indexerResolver({
        onTest: () => {
          throw new ApiRequestError(
            400,
            {
              message: 'indexer settings validation failed',
              errors: [
                { field: 'settings.base_url', message: 'must be an http(s) URL' },
              ],
            },
            '/api/v1/indexer/test',
          );
        },
      }),
    );
    renderWithProviders(<IndexerSettings />, { fetcher });

    await user.click(await screen.findByTestId('provider-card-1'));
    await user.click(screen.getByRole('button', { name: 'Test' }));

    const row = await screen.findByTestId('schema-field-base_url');
    expect(within(row).getByRole('alert')).toHaveTextContent(
      'must be an http(s) URL',
    );
  });

  it('FRG-UI-008 — Test success renders the structured pass message', async () => {
    const user = userEvent.setup();
    const { spy, fetcher } = fakeFetcher(indexerResolver());
    renderWithProviders(<IndexerSettings />, { fetcher });

    await user.click(await screen.findByTestId('provider-card-1'));
    await user.click(screen.getByRole('button', { name: 'Test' }));

    expect(await screen.findByTestId('test-result')).toHaveTextContent(
      'indexer reachable; capabilities retrieved',
    );
    expect(spy).toHaveBeenCalledWith(
      '/api/v1/indexer/test',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('FRG-UI-008 — a degraded indexer pass is surfaced as a warning, not a clean pass', async () => {
    const user = userEvent.setup();
    const { fetcher } = fakeFetcher(
      indexerResolver({
        onTest: () => ({
          success: true,
          message: 'indexer reachable',
          categories: { 7030: 'Books/Comics' },
          degraded: true,
        }),
      }),
    );
    renderWithProviders(<IndexerSettings />, { fetcher });

    await user.click(await screen.findByTestId('provider-card-1'));
    await user.click(screen.getByRole('button', { name: 'Test' }));

    const result = await screen.findByTestId('test-result');
    expect(result).toHaveTextContent('indexer reachable');
    // degraded=true must read as a warning, never a clean pass.
    expect(result).toHaveTextContent(
      'Indexer responded but with degraded capabilities',
    );
  });

  it('FRG-UI-008 — a secret echoed by a regressed backend never reaches the password input', async () => {
    const user = userEvent.setup();
    // Simulate a backend that WRONGLY echoes the secret in the row settings.
    const leaked = [
      {
        ...mockIndexers[0],
        settings: { ...mockIndexers[0].settings, api_key: 'leaked-secret' },
      },
    ];
    const { fetcher } = fakeFetcher(indexerResolver({ rows: () => leaked }));
    renderWithProviders(<IndexerSettings />, { fetcher });

    await user.click(await screen.findByTestId('provider-card-1'));
    const dialog = screen.getByRole('dialog', { name: 'Edit Indexer — Newznab' });
    const apiKey = within(dialog).getByLabelText('API Key') as HTMLInputElement;
    // Defense in depth: the secret is stripped when seeding, input stays empty.
    expect(apiKey.value).toBe('');
  });

  it('FRG-UI-008 — a valid configuration saves via POST and the new card renders enabled', async () => {
    const user = userEvent.setup();
    const rows: ProviderResource[] = [];
    const { spy, fetcher } = fakeFetcher(
      indexerResolver({
        rows: () => rows,
        onSave: (_path, init) => {
          const body = init?.body as Record<string, unknown>;
          const created: ProviderResource = {
            ...(body as unknown as ProviderResource),
            id: 9,
            protocol: 'usenet',
            settings: body.settings as ProviderResource['settings'],
          };
          rows.push(created);
          return created;
        },
      }),
    );
    renderWithProviders(<IndexerSettings />, { fetcher });

    await user.click(await screen.findByRole('button', { name: 'Add Indexer' }));
    const dialog = screen.getByRole('dialog', { name: 'Add Indexer — Newznab' });

    await user.type(within(dialog).getByLabelText('Name'), 'NZB.su');
    await user.type(
      within(dialog).getByLabelText('URL'),
      'https://api.nzb.su',
    );
    await user.type(within(dialog).getByLabelText('API Key'), 'fresh-key');
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        '/api/v1/indexer',
        expect.objectContaining({
          method: 'POST',
          body: expect.objectContaining({
            implementation: 'newznab',
            name: 'NZB.su',
            enabled: true,
            enable_rss: true,
            settings: expect.objectContaining({
              base_url: 'https://api.nzb.su',
              api_key: 'fresh-key',
            }),
          }),
        }),
      ),
    );

    // Modal closes and the refetched list renders the new card enabled.
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
    );
    const card = await screen.findByTestId('provider-card-9');
    expect(within(card).getByRole('switch')).toHaveAttribute('aria-checked', 'true');
  });
});
