import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/renderWithProviders';
import { fakeFetcher } from '../../../test/fakeFetcher';
import type { ComicVineConfig } from '../../../api/types';
import type { FetcherInit } from '../../../api/fetcher';
import { NonComicPublishers } from './NonComicPublishers';

/*
 * FRG-UI-046 — the library-wide publisher-filtering panel in Settings ->
 * General, replacing the removed per-source Sources-screen editor
 * (FRG-SRC-012). Plain-language copy, curated removable defaults shown like
 * any other entry, and the env-managed / next-sync / sticky-decision notes
 * carried over from the old panel's safety story.
 */

const DEFAULT_LIST: ComicVineConfig['non_comic_publishers'] = {
  value: 'Example Games, Example Tech Press',
  source: 'default',
};

function config(overrides: Partial<ComicVineConfig> = {}): ComicVineConfig {
  return {
    comicvine_api_key: { configured: true, source: 'file' },
    comicvine_ignored_publishers: { value: '', source: 'file' },
    non_comic_publishers: DEFAULT_LIST,
    ...overrides,
  };
}

function resolver(
  getConfig: () => ComicVineConfig,
  onPut?: (init?: FetcherInit) => unknown,
) {
  return (path: string, init?: FetcherInit): unknown => {
    if (path === '/api/v1/config/general') {
      if (init?.method === 'PUT') {
        return onPut ? onPut(init) : getConfig();
      }
      return getConfig();
    }
    throw new Error(`unexpected request: ${init?.method ?? 'GET'} ${path}`);
  };
}

describe('FRG-UI-046: Settings publisher-filtering panel', () => {
  it('FRG-UI-046 — the panel shows the curated defaults, each removable', async () => {
    const { fetcher } = fakeFetcher(resolver(() => config()));
    renderWithProviders(<NonComicPublishers />, { fetcher });

    expect(
      await screen.findByTestId('non-comic-publisher-Example Games'),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('non-comic-publisher-Example Tech Press'),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('non-comic-publisher-remove-Example Games'),
    ).toBeInTheDocument();
  });

  it('FRG-UI-046 — adding a publisher and saving PUTs the whole list as a comma-separated string', async () => {
    const user = userEvent.setup();
    const { spy, fetcher } = fakeFetcher(
      resolver(
        () => config(),
        (init) => {
          const body = init?.body as { non_comic_publishers?: string };
          expect(body.non_comic_publishers).toBe(
            'Example Games, Example Tech Press, Example Art Books',
          );
          return config({
            non_comic_publishers: {
              value: 'Example Games, Example Tech Press, Example Art Books',
              source: 'file',
            },
          });
        },
      ),
    );
    renderWithProviders(<NonComicPublishers />, { fetcher });

    await screen.findByTestId('non-comic-publisher-Example Games');
    await user.type(
      screen.getByTestId('non-comic-publishers-input'),
      'Example Art Books',
    );
    await user.click(screen.getByTestId('non-comic-publishers-add'));
    await user.click(screen.getByTestId('non-comic-publishers-save'));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        '/api/v1/config/general',
        expect.objectContaining({ method: 'PUT' }),
      ),
    );
    expect(
      await screen.findByTestId('non-comic-publishers-saved'),
    ).toBeInTheDocument();
  });

  it('FRG-UI-046 — removing a default and saving excludes it from the PUT body', async () => {
    const user = userEvent.setup();
    const { fetcher } = fakeFetcher(
      resolver(
        () => config(),
        (init) => {
          const body = init?.body as { non_comic_publishers?: string };
          expect(body.non_comic_publishers).toBe('Example Tech Press');
          return config({
            non_comic_publishers: { value: 'Example Tech Press', source: 'file' },
          });
        },
      ),
    );
    renderWithProviders(<NonComicPublishers />, { fetcher });

    await screen.findByTestId('non-comic-publisher-Example Games');
    await user.click(screen.getByTestId('non-comic-publisher-remove-Example Games'));
    await user.click(screen.getByTestId('non-comic-publishers-save'));

    await waitFor(() =>
      expect(
        screen.queryByTestId('non-comic-publisher-Example Games'),
      ).not.toBeInTheDocument(),
    );
  });

  it('FRG-UI-046 — the panel describes non-comic filtering in plain user terms, with no per-genre or implementation framing', async () => {
    const { fetcher } = fakeFetcher(resolver(() => config()));
    renderWithProviders(<NonComicPublishers />, { fetcher });

    const panel = await screen.findByTestId('non-comic-publishers-panel');
    expect(panel).toHaveTextContent('RPG rulebooks');
    expect(panel).toHaveTextContent('tech-book PDFs');
    expect(panel).toHaveTextContent('art books');
    expect(panel).toHaveTextContent('files them as Other');
    expect(panel.textContent?.toLowerCase()).not.toContain('escape hatch');
  });

  it('FRG-UI-046 — the panel states the next-sync timing and that reviewed items do not move', async () => {
    const { fetcher } = fakeFetcher(resolver(() => config()));
    renderWithProviders(<NonComicPublishers />, { fetcher });

    const panel = await screen.findByTestId('non-comic-publishers-panel');
    expect(panel).toHaveTextContent('next sync');
    expect(panel).toHaveTextContent(
      "already matched or ignored don't move",
    );
  });

  it('FRG-UI-046 — an env-managed list renders read-only guidance, not an editor', async () => {
    const { fetcher } = fakeFetcher(
      resolver(() =>
        config({
          non_comic_publishers: { value: 'Env House', source: 'env' },
        }),
      ),
    );
    renderWithProviders(<NonComicPublishers />, { fetcher });

    const note = await screen.findByTestId('non-comic-publishers-env-managed');
    expect(note).toHaveTextContent('FORAGERR_NON_COMIC_PUBLISHERS');
    expect(note).toHaveTextContent('managed outside the UI');
    expect(
      screen.queryByTestId('non-comic-publishers-input'),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId('non-comic-publishers-save'),
    ).not.toBeInTheDocument();
  });
});

/*
 * The old per-source panel's help text read "the RPG-sourcebook escape
 * hatch" (FRG-SRC-012's original copy) — the owner flagged that phrase by
 * name as implementation-leaking jargon a user should never see. A rendered
 * assertion only proves the one mounted panel is clean; this scans every
 * shipped source file so the phrase cannot resurface anywhere else in the
 * frontend (a stray copy-paste in another screen, a leftover code comment
 * that later gets promoted to UI text).
 */
const HERE = dirname(fileURLToPath(import.meta.url));
const SRC_ROOT = join(HERE, '..', '..', '..');

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.(ts|tsx)$/.test(entry.name))
      out.push(full);
  }
  return out;
}

describe('FRG-UI-046: no implementation-jargon framing anywhere in the frontend', () => {
  it('FRG-UI-046 — "escape hatch" appears in no frontend source file', () => {
    const offenders: string[] = [];
    for (const file of walk(SRC_ROOT)) {
      const text = readFileSync(file, 'utf8').toLowerCase();
      if (text.includes('escape hatch')) offenders.push(file);
    }
    expect(offenders).toEqual([]);
  });
});
