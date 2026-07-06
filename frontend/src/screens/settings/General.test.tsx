import { describe, it, expect } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import { ApiRequestError, type FetcherInit } from '../../api/fetcher';
import type { ComicVineConfig } from '../../api/types';
import { General } from './General';

/*
 * FRG-UI-020 — Settings -> General: the ComicVine credential settings screen
 * (FRG-API-018's UI). Every delta-spec scenario against the injected fake
 * fetcher (no live backend): the masked write-only key field never echoes the
 * stored key, the environment-managed state renders read-only guidance
 * instead of a shadow-able editor, a save persists + updates the cached
 * status, a blank save keeps the stored key, an (edge-case) env-managed
 * rejection renders gracefully, and the Test button reports both outcomes
 * without ever showing the key.
 */

const UNSET: ComicVineConfig = {
  comicvine_api_key: { configured: false, source: 'unset' },
};

const FILE_SET: ComicVineConfig = {
  comicvine_api_key: { configured: true, source: 'file' },
};

const ENV_SET: ComicVineConfig = {
  comicvine_api_key: { configured: true, source: 'environment' },
};

interface Overrides {
  config?: () => ComicVineConfig;
  onPut?: (init?: FetcherInit) => unknown;
  onTest?: (init?: FetcherInit) => unknown;
}

function resolver(o: Overrides = {}) {
  return (path: string, init?: FetcherInit): unknown => {
    if (path === '/api/v1/config/general') {
      if (init?.method === 'PUT') {
        if (o.onPut) return o.onPut(init);
        return FILE_SET;
      }
      return o.config ? o.config() : UNSET;
    }
    if (path === '/api/v1/config/comicvine/test' && init?.method === 'POST') {
      if (o.onTest) return o.onTest(init);
      return { success: true, message: 'ComicVine reachable.' };
    }
    throw new Error(`unexpected request: ${init?.method ?? 'GET'} ${path}`);
  };
}

describe('FRG-UI-020: Settings -> General', () => {
  it('FRG-UI-020 — an unset key renders an empty editable field with helper text', async () => {
    const { fetcher } = fakeFetcher(resolver({ config: () => UNSET }));
    renderWithProviders(<General />, { fetcher });

    const input = await screen.findByLabelText('ComicVine API Key');
    expect(input).toHaveValue('');
    expect(input).not.toHaveAttribute('placeholder', '••••••••');
    expect(
      screen.getByTestId('comicvine-key-unset-hint'),
    ).toHaveTextContent('No ComicVine API key is configured yet');
    expect(
      screen.queryByTestId('comicvine-key-env-managed'),
    ).not.toBeInTheDocument();
  });

  it('FRG-UI-020 — a file-set key renders masked with a "currently set" hint and never echoes the value', async () => {
    const { fetcher } = fakeFetcher(resolver({ config: () => FILE_SET }));
    renderWithProviders(<General />, { fetcher });

    const input = await screen.findByLabelText('ComicVine API Key');
    expect(input).toHaveValue('');
    expect(input).toHaveAttribute('placeholder', '••••••••');
    expect(screen.getByTestId('secret-hint-comicvine_api_key')).toHaveTextContent(
      'Currently set',
    );
    // The stored key must never appear anywhere in the DOM.
    expect(document.body.innerHTML).not.toMatch(/file-stored-key/);
  });

  it('FRG-UI-020 — an environment-supplied key renders read-only guidance, not an editor', async () => {
    const { fetcher } = fakeFetcher(resolver({ config: () => ENV_SET }));
    renderWithProviders(<General />, { fetcher });

    const note = await screen.findByTestId('comicvine-key-env-managed');
    expect(note).toHaveTextContent('FORAGERR_COMICVINE_API_KEY');
    expect(note).toHaveTextContent('managed outside the UI');
    expect(
      screen.queryByLabelText('ComicVine API Key'),
    ).not.toBeInTheDocument();
    // No shadow-able editor means no save action either.
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
  });

  it('FRG-UI-020 — saving a new key persists it and updates the cached credential status', async () => {
    const user = userEvent.setup();
    const { spy, fetcher } = fakeFetcher(
      resolver({
        config: () => FILE_SET,
        onPut: (init) => {
          const body = init?.body as { comicvine_api_key: string };
          expect(body.comicvine_api_key).toBe('new-key-value');
          return FILE_SET;
        },
      }),
    );
    renderWithProviders(<General />, { fetcher });

    const input = await screen.findByLabelText('ComicVine API Key');
    await user.type(input, 'new-key-value');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        '/api/v1/config/general',
        expect.objectContaining({ method: 'PUT' }),
      ),
    );
    // Write-only: the field goes blank again after a successful save, never
    // echoing what was just persisted.
    await waitFor(() => expect(input).toHaveValue(''));
  });

  it('FRG-UI-020 — a blank save keeps the stored key rather than clearing it', async () => {
    const user = userEvent.setup();
    const { spy, fetcher } = fakeFetcher(
      resolver({
        config: () => FILE_SET,
        onPut: (init) => {
          const body = init?.body as { comicvine_api_key: string };
          expect(body.comicvine_api_key).toBe('');
          // The endpoint's own contract: a blank update keeps the stored
          // value, so the reported status is unchanged.
          return FILE_SET;
        },
      }),
    );
    renderWithProviders(<General />, { fetcher });

    await screen.findByLabelText('ComicVine API Key');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        '/api/v1/config/general',
        expect.objectContaining({ method: 'PUT' }),
      ),
    );
    // Still configured/masked afterward — nothing was cleared.
    expect(
      screen.getByTestId('secret-hint-comicvine_api_key'),
    ).toBeInTheDocument();
  });

  it('FRG-UI-020 — an environment-managed save rejection renders gracefully', async () => {
    const user = userEvent.setup();
    const { fetcher } = fakeFetcher(
      resolver({
        config: () => UNSET,
        onPut: () => {
          throw new ApiRequestError(
            409,
            {
              message: 'ComicVine API key is set by FORAGERR_COMICVINE_API_KEY',
              errors: [
                {
                  field: 'comicvine_api_key',
                  message:
                    'set by the FORAGERR_COMICVINE_API_KEY environment variable',
                },
              ],
            },
            '/api/v1/config/general',
          );
        },
      }),
    );
    renderWithProviders(<General />, { fetcher });

    const input = await screen.findByLabelText('ComicVine API Key');
    await user.type(input, 'attempted-key');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(
        'FORAGERR_COMICVINE_API_KEY',
      ),
    );
  });

  it('FRG-UI-020 — Test reports connectivity success without ever showing the key', async () => {
    const user = userEvent.setup();
    const { spy, fetcher } = fakeFetcher(
      resolver({
        config: () => FILE_SET,
        onTest: () => ({ success: true, message: 'ComicVine reachable.' }),
      }),
    );
    renderWithProviders(<General />, { fetcher });

    await screen.findByLabelText('ComicVine API Key');
    await user.click(screen.getByRole('button', { name: 'Test' }));

    const result = await screen.findByTestId('comicvine-test-result');
    expect(result).toHaveTextContent('ComicVine reachable.');
    expect(spy).toHaveBeenCalledWith(
      '/api/v1/config/comicvine/test',
      expect.objectContaining({ method: 'POST' }),
    );
    // Test never sends the (unsaved, still-typed) form value.
    expect(spy).not.toHaveBeenCalledWith(
      '/api/v1/config/comicvine/test',
      expect.objectContaining({ body: expect.anything() }),
    );
  });

  it('FRG-UI-020 — a field-less Test reachability failure renders a form-level message, not a "test result" box', async () => {
    const user = userEvent.setup();
    const { fetcher } = fakeFetcher(
      resolver({
        config: () => FILE_SET,
        onTest: () => {
          throw new ApiRequestError(
            400,
            { message: 'ComicVine did not respond', errors: [{ field: null, message: 'ComicVine did not respond' }] },
            '/api/v1/config/comicvine/test',
          );
        },
      }),
    );
    renderWithProviders(<General />, { fetcher });

    await screen.findByLabelText('ComicVine API Key');
    await user.click(screen.getByRole('button', { name: 'Test' }));

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(
        'ComicVine did not respond',
      ),
    );
    expect(screen.queryByTestId('comicvine-test-result')).not.toBeInTheDocument();
  });

  it('FRG-UI-020 — a Test auth failure attaches to the key field, mirroring the provider Test contract', async () => {
    const user = userEvent.setup();
    const { fetcher } = fakeFetcher(
      resolver({
        config: () => FILE_SET,
        onTest: () => {
          throw new ApiRequestError(
            400,
            {
              message: 'ComicVine rejected the API key',
              errors: [
                { field: 'comicvine_api_key', message: 'invalid API key' },
              ],
            },
            '/api/v1/config/comicvine/test',
          );
        },
      }),
    );
    renderWithProviders(<General />, { fetcher });

    await screen.findByLabelText('ComicVine API Key');
    await user.click(screen.getByRole('button', { name: 'Test' }));

    const row = await screen.findByTestId('schema-field-comicvine_api_key');
    expect(within(row).getByRole('alert')).toHaveTextContent('invalid API key');
    expect(screen.queryByTestId('comicvine-test-result')).not.toBeInTheDocument();
  });

  it('FRG-UI-020 — Test is disabled while the field has unsaved edits, with a hint to save first', async () => {
    const user = userEvent.setup();
    const { fetcher } = fakeFetcher(resolver({ config: () => FILE_SET }));
    renderWithProviders(<General />, { fetcher });

    const input = await screen.findByLabelText('ComicVine API Key');
    expect(screen.getByRole('button', { name: 'Test' })).toBeEnabled();

    await user.type(input, 'unsaved-value');

    expect(screen.getByRole('button', { name: 'Test' })).toBeDisabled();
    expect(
      screen.getByTestId('comicvine-test-disabled-hint'),
    ).toHaveTextContent('Save your changes before testing');
  });
});
