import { describe, it, expect } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import { ApiRequestError, type FetcherInit } from '../../api/fetcher';
import {
  mockDownloadClients,
  mockDownloadClientSchemas,
} from '../../test/providerMocks';
import { DownloadClientSettings } from './DownloadClientSettings';

/*
 * FRG-UI-009 — download-client settings on the SAME schema-form renderer:
 * SABnzbd category/priority/remove-completed come from the schema + kind
 * config, POST /downloadclient/test drives the Test button, and secrets stay
 * write-only. Renderer-identity is enforced structurally by the audit test in
 * rendererReuse.audit.test.ts; here we prove the rendered form IS the shared
 * renderer's output (its data-schema-form marker) with the right fields.
 */

function dlResolver(overrides?: {
  onTest?: (init?: FetcherInit) => unknown;
}) {
  return (path: string, init?: FetcherInit): unknown => {
    if (path === '/api/v1/downloadclient/schema') return mockDownloadClientSchemas;
    if (path === '/api/v1/downloadclient/test') {
      if (overrides?.onTest) return overrides.onTest(init);
      return {
        success: true,
        message: 'SABnzbd reachable',
        version: '4.3.2',
        warnings: ['category "comics" does not exist yet'],
      };
    }
    if (init?.method === 'POST' || init?.method === 'PUT') {
      return { ...mockDownloadClients[0], ...(init.body as object) };
    }
    if (path === '/api/v1/downloadclient') return mockDownloadClients;
    throw new Error(`unexpected path: ${path}`);
  };
}

describe('FRG-UI-009: download-client settings reuse the generic renderer', () => {
  it('FRG-UI-009 — the SABnzbd modal is produced by the shared schema-form renderer with category, priority, and remove-completed fields', async () => {
    const user = userEvent.setup();
    const { fetcher } = fakeFetcher(dlResolver());
    renderWithProviders(<DownloadClientSettings />, { fetcher });

    // Advanced on, so the (advanced) priority select is visible too.
    await user.click(
      await screen.findByRole('button', { name: 'Show Advanced' }),
    );
    await user.click(screen.getByTestId('provider-card-1'));
    const dialog = screen.getByRole('dialog', {
      name: 'Edit Download Client — SABnzbd',
    });

    // Every form region inside the modal is the shared renderer's output.
    const forms = dialog.querySelectorAll('[data-schema-form="true"]');
    expect(forms.length).toBeGreaterThan(0);
    expect(dialog.querySelectorAll('input, select, textarea').length).toBe(
      Array.from(forms).reduce(
        (n, f) => n + f.querySelectorAll('input, select, textarea').length,
        0,
      ),
    );

    // Schema-driven fields: category (textbox), priority (select w/ options).
    expect(within(dialog).getByLabelText('Category')).toHaveValue('comics');
    const priority = within(dialog).getByLabelText('Priority');
    expect(priority.tagName).toBe('SELECT');
    expect(within(dialog).getByRole('option', { name: 'Force' })).toBeInTheDocument();

    // Kind-config row field rendered by the same renderer: remove-completed.
    expect(within(dialog).getByLabelText('Remove Completed')).toBeChecked();
  });

  it('FRG-UI-009 — Test invokes POST /downloadclient/test and renders the structured pass result', async () => {
    const user = userEvent.setup();
    const { spy, fetcher } = fakeFetcher(dlResolver());
    renderWithProviders(<DownloadClientSettings />, { fetcher });

    await user.click(await screen.findByTestId('provider-card-1'));
    await user.click(screen.getByRole('button', { name: 'Test' }));

    const result = await screen.findByTestId('test-result');
    expect(result).toHaveTextContent('SABnzbd reachable');
    expect(result).toHaveTextContent('category "comics" does not exist yet');
    expect(spy).toHaveBeenCalledWith(
      '/api/v1/downloadclient/test',
      expect.objectContaining({
        method: 'POST',
        body: expect.objectContaining({ implementation: 'sabnzbd' }),
      }),
    );
  });

  it('FRG-UI-009 — a field-precise test failure lands on the field it concerns', async () => {
    const user = userEvent.setup();
    const { fetcher } = fakeFetcher(
      dlResolver({
        onTest: () => {
          throw new ApiRequestError(
            400,
            {
              message: 'download client unreachable',
              errors: [{ field: 'base_url', message: 'connection refused' }],
            },
            '/api/v1/downloadclient/test',
          );
        },
      }),
    );
    renderWithProviders(<DownloadClientSettings />, { fetcher });

    await user.click(await screen.findByTestId('provider-card-1'));
    await user.click(screen.getByRole('button', { name: 'Test' }));

    const row = await screen.findByTestId('schema-field-base_url');
    expect(within(row).getByRole('alert')).toHaveTextContent('connection refused');
  });

  it('FRG-UI-009 — the stored SABnzbd API key stays write-only: empty input, placeholder, blank omitted on save', async () => {
    const user = userEvent.setup();
    const { spy, fetcher } = fakeFetcher(dlResolver());
    renderWithProviders(<DownloadClientSettings />, { fetcher });

    await user.click(await screen.findByTestId('provider-card-1'));
    const dialog = screen.getByRole('dialog', {
      name: 'Edit Download Client — SABnzbd',
    });

    const apiKey = within(dialog).getByLabelText('API Key') as HTMLInputElement;
    expect(apiKey).toHaveAttribute('type', 'password');
    expect(apiKey.value).toBe('');
    expect(apiKey).toHaveAttribute('placeholder', '••••••••');

    await user.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        '/api/v1/downloadclient/1',
        expect.objectContaining({ method: 'PUT' }),
      ),
    );
    const putCall = spy.mock.calls.find(
      ([p, i]) => p === '/api/v1/downloadclient/1' && i?.method === 'PUT',
    );
    const body = putCall?.[1]?.body as { settings: Record<string, unknown> };
    // Blank secret omitted → "keep the stored value"; never sent as ''.
    expect('api_key' in body.settings).toBe(false);
    expect(body.settings.base_url).toBe('http://sab:8080');
  });

  it('FRG-UI-009 — the add picker lists every implementation from the schema (DDL appears with zero new UI code)', async () => {
    const user = userEvent.setup();
    const { fetcher } = fakeFetcher(dlResolver());
    renderWithProviders(<DownloadClientSettings />, { fetcher });

    await user.click(
      await screen.findByRole('button', { name: 'Show Advanced' }),
    );
    await user.click(screen.getByRole('button', { name: 'Add Download Client' }));
    await user.click(screen.getByRole('button', { name: /Built-in DDL/ }));

    const dialog = screen.getByRole('dialog', {
      name: 'Add Download Client — Built-in DDL',
    });
    expect(within(dialog).getByLabelText('Host Priority')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('Prefer Upscaled')).toBeInTheDocument();
  });
});
