import { describe, it, expect } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/renderWithProviders';
import { fakeFetcher } from '../../test/fakeFetcher';
import { ApiRequestError, type FetcherInit } from '../../api/fetcher';
import { makeCommand, makeSeriesResource, pageOf } from '../../test/mockData';
import type {
  NamingConfig,
  NamingTokens,
  RenamePreviewEntry,
} from '../../api/types';
import {
  MediaManagement,
  type MediaManagementConfigWithDuplicates,
} from './MediaManagement';

/*
 * FRG-UI-012 — the media-management / naming settings screen. Every delta-spec
 * scenario is covered here against the injected fake fetcher (no live backend):
 * standard fields render through the shared SchemaForm and persist via the two
 * config PUTs; the live example recomputes client-side as the template is typed;
 * the `?` popover renders the one shared token vocabulary; a field-precise 4xx
 * attaches to its field; and the per-series rename preview only mutates on an
 * explicit confirm.
 */

const NAMING: NamingConfig = {
  rename_enabled: true,
  file_naming_template: '{Series Title} {Issue Number:000} ({Year}) [__{IssueId}__]',
  folder_naming_template: '{Series Title} ({Year})',
  replace_illegal_characters: true,
};

const MM: MediaManagementConfigWithDuplicates = {
  import_transfer_mode: 'move',
  library_import_mode: 'in_place',
  recycle_bin_path: '',
  recycle_bin_retention_days: 0,
  duplicate_constraint: 'larger-size',
  duplicate_dump_path: '',
};

const TOKENS: NamingTokens = {
  aliases: {
    'series title': 'series_title',
    'series cleantitle': 'series_cleantitle',
    cleantitle: 'series_cleantitle',
    volume: 'volume',
    year: 'year',
    issue: 'issue',
    'issue number': 'issue',
    'issue title': 'issue_title',
    classification: 'classification',
    booktype: 'booktype',
    'release group': 'release_group',
    issueid: 'issue_id',
    'issue id': 'issue_id',
    publisher: 'publisher',
  },
  defaults: {
    file_naming_template: NAMING.file_naming_template,
    folder_naming_template: NAMING.folder_naming_template,
  },
};

const SERIES = [
  makeSeriesResource({ id: 7, title: 'Invincible', sort_title: 'invincible' }),
];

const RENAME_ROWS: RenamePreviewEntry[] = [
  {
    issueFileId: 101,
    issueId: 5,
    existingPath: '/comics/Invincible/wrong scan.cbz',
    newPath: '/comics/Invincible/Invincible 001 (2003) [__5__].cbz',
  },
];

interface Overrides {
  naming?: () => NamingConfig;
  mm?: () => MediaManagementConfigWithDuplicates;
  tokens?: () => NamingTokens;
  onTokens?: () => unknown;
  onPutNaming?: (init?: FetcherInit) => unknown;
  onPutMm?: (init?: FetcherInit) => unknown;
  renameRows?: () => RenamePreviewEntry[];
  onPostRename?: (init?: FetcherInit) => unknown;
  command?: () => ReturnType<typeof makeCommand>;
  /** The paged command-list the active-rename probe reads (default: empty). */
  commandList?: () => ReturnType<typeof makeCommand>[];
}

function resolver(o: Overrides = {}) {
  return (path: string, init?: FetcherInit): unknown => {
    if (path === '/api/v1/config/naming/tokens') {
      if (o.onTokens) return o.onTokens();
      return o.tokens ? o.tokens() : TOKENS;
    }
    if (path === '/api/v1/config/naming') {
      if (init?.method === 'PUT') {
        return o.onPutNaming ? o.onPutNaming(init) : (init.body as NamingConfig);
      }
      return o.naming ? o.naming() : NAMING;
    }
    if (path === '/api/v1/config/mediamanagement') {
      if (init?.method === 'PUT') {
        return o.onPutMm ? o.onPutMm(init) : (init.body as MediaManagementConfigWithDuplicates);
      }
      return o.mm ? o.mm() : MM;
    }
    if (path.startsWith('/api/v1/series?')) return pageOf(SERIES);
    if (path.startsWith('/api/v1/rename?')) {
      return o.renameRows ? o.renameRows() : RENAME_ROWS;
    }
    if (path === '/api/v1/rename' && init?.method === 'POST') {
      return o.onPostRename ? o.onPostRename(init) : makeCommand({ id: 55, name: 'rename-series', status: 'queued' });
    }
    // The active-rename probe (paged list) — distinct from the by-id lookup.
    if (path.startsWith('/api/v1/command?')) {
      return pageOf(o.commandList ? o.commandList() : []);
    }
    if (path.startsWith('/api/v1/command/')) {
      return o.command ? o.command() : makeCommand({ id: 55, name: 'rename-series', status: 'completed' });
    }
    throw new Error(`unexpected path: ${path}`);
  };
}

describe('FRG-UI-012: standard fields via SchemaForm + save', () => {
  it('FRG-UI-012 — standard fields render through the shared SchemaForm renderer', async () => {
    const { fetcher } = fakeFetcher(resolver());
    renderWithProviders(<MediaManagement />, { fetcher });

    // The renderer stamps data-schema-form + schema-field-<name> testids.
    const importField = await screen.findByTestId('schema-field-import_transfer_mode');
    expect(within(importField).getByLabelText('Import Using').tagName).toBe('SELECT');
    expect(screen.getByTestId('schema-field-rename_enabled')).toBeInTheDocument();
    expect(screen.getByTestId('schema-field-recycle_bin_path')).toBeInTheDocument();
    expect(screen.getByTestId('schema-field-recycle_bin_retention_days')).toBeInTheDocument();
  });

  it('FRG-UI-012 — changing a standard field and saving persists it through the config PUT', async () => {
    const user = userEvent.setup();
    const { spy, fetcher } = fakeFetcher(resolver());
    renderWithProviders(<MediaManagement />, { fetcher });

    const importField = await screen.findByTestId('schema-field-import_transfer_mode');
    await user.selectOptions(within(importField).getByLabelText('Import Using'), 'copy');

    const save = screen.getByRole('button', { name: 'Save Changes' });
    await user.click(save);

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        '/api/v1/config/mediamanagement',
        expect.objectContaining({
          method: 'PUT',
          body: expect.objectContaining({ import_transfer_mode: 'copy' }),
        }),
      ),
    );
    // The naming resource was NOT touched — only the dirty resource is PUT.
    expect(
      spy.mock.calls.filter(
        ([p, i]) => p === '/api/v1/config/naming' && i?.method === 'PUT',
      ),
    ).toHaveLength(0);
  });

  it('FRG-UI-012 — the save bar is inert until a field changes', async () => {
    const { fetcher } = fakeFetcher(resolver());
    renderWithProviders(<MediaManagement />, { fetcher });
    const button = await screen.findByRole('button', { name: 'No Changes' });
    expect(button).toBeDisabled();
  });

  it('FRG-UI-012 — clearing a number field back to its saved 0 does not arm the save bar (no dirty-loop)', async () => {
    const user = userEvent.setup();
    // MM.recycle_bin_retention_days is 0; the schema number widget emits '' when
    // cleared. Diffing raw ('' !== 0) would read dirty forever; normalize (to the
    // PUT-payload form, 0) makes the cleared field equal its saved value.
    const { fetcher } = fakeFetcher(resolver());
    renderWithProviders(<MediaManagement />, { fetcher });

    const days = await screen.findByLabelText('Recycle Bin Cleanup (days)');
    await user.clear(days);

    // The form is back to its saved state — the save bar disarms, not stuck dirty.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'No Changes' })).toBeDisabled(),
    );
  });
});

describe('FRG-PP-014: duplicate handling settings', () => {
  it('FRG-PP-014 — the duplicate constraint and dump folder fields render in the Duplicate Handling section', async () => {
    const { fetcher } = fakeFetcher(resolver());
    renderWithProviders(<MediaManagement />, { fetcher });

    const constraint = await screen.findByTestId('schema-field-duplicate_constraint');
    const select = within(constraint).getByLabelText('Duplicate Constraint');
    expect(select.tagName).toBe('SELECT');
    // Seeded from the GET (larger-size is the documented default).
    expect(select).toHaveValue('larger-size');
    expect(within(constraint).getByRole('option', { name: 'Preferred format' })).toBeInTheDocument();
    expect(screen.getByTestId('schema-field-duplicate_dump_path')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Duplicate Handling' })).toBeInTheDocument();
  });

  it('FRG-PP-014 — changing the constraint and dump folder persists both through the media-management PUT', async () => {
    const user = userEvent.setup();
    const { spy, fetcher } = fakeFetcher(resolver());
    renderWithProviders(<MediaManagement />, { fetcher });

    const constraint = await screen.findByTestId('schema-field-duplicate_constraint');
    await user.selectOptions(
      within(constraint).getByLabelText('Duplicate Constraint'),
      'preferred-format',
    );
    await user.type(
      screen.getByLabelText('Duplicate Dump Folder'),
      '/comics/.duplicates',
    );
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        '/api/v1/config/mediamanagement',
        expect.objectContaining({
          method: 'PUT',
          body: expect.objectContaining({
            duplicate_constraint: 'preferred-format',
            duplicate_dump_path: '/comics/.duplicates',
          }),
        }),
      ),
    );
  });

  it('FRG-PP-014 — a field-precise 4xx on the dump folder attaches to its field', async () => {
    const user = userEvent.setup();
    const { fetcher } = fakeFetcher(
      resolver({
        onPutMm: () => {
          throw new ApiRequestError(
            400,
            {
              message: 'config validation failed',
              errors: [
                {
                  field: 'settings.duplicate_dump_path',
                  message: 'path /nope does not exist and its parent is not a writable directory',
                },
              ],
            },
            '/api/v1/config/mediamanagement',
          );
        },
      }),
    );
    renderWithProviders(<MediaManagement />, { fetcher });

    await user.type(await screen.findByLabelText('Duplicate Dump Folder'), '/nope');
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    const field = screen.getByTestId('schema-field-duplicate_dump_path');
    await waitFor(() =>
      expect(within(field).getByRole('alert')).toHaveTextContent(
        'not a writable directory',
      ),
    );
  });
});

describe('FRG-UI-012: live example preview', () => {
  it('FRG-UI-012 — the file example recomputes live as the template is edited, no save round-trip', async () => {
    const user = userEvent.setup();
    const { spy, fetcher } = fakeFetcher(resolver());
    renderWithProviders(<MediaManagement />, { fetcher });

    const example = await screen.findByTestId('example-file_naming_template');
    // Seeded from the default template against the sample issue.
    expect(example).toHaveTextContent('Saga 005 (2012) [__12345__].cbz');

    const input = within(
      screen.getByTestId('template-field-file_naming_template'),
    ).getByRole('textbox');
    await user.clear(input);
    await user.type(input, '{{Series Title} #{{Issue Number:0000}');

    // Recomputed client-side (padding widened to 0000 -> 0005) with NO PUT.
    await waitFor(() => expect(example).toHaveTextContent('Saga #0005.cbz'));
    expect(
      spy.mock.calls.filter(([, i]) => i?.method === 'PUT'),
    ).toHaveLength(0);
  });
});

describe('FRG-UI-012: token help popover', () => {
  it('FRG-UI-012 — the `?` popover renders every token from the shared vocabulary', async () => {
    const user = userEvent.setup();
    const { fetcher } = fakeFetcher(resolver());
    renderWithProviders(<MediaManagement />, { fetcher });

    const field = await screen.findByTestId('template-field-file_naming_template');
    await user.click(within(field).getByRole('button', { name: /token help/i }));

    const help = await screen.findByTestId('token-help-file_naming_template');
    // Tokens derived from the fetched alias table (no hand-maintained list).
    expect(within(help).getByText('{Series Title}')).toBeInTheDocument();
    expect(within(help).getByText('{Issue Number}')).toBeInTheDocument();
    expect(within(help).getByText('{Publisher}')).toBeInTheDocument();
    // A synonym line proves the grouping comes from the alias table.
    expect(within(help).getByText(/issue number, issue/)).toBeInTheDocument();
  });
});

describe('FRG-UI-012: field-precise validation errors', () => {
  it('FRG-UI-012 — a field-precise 4xx attaches to its template field via the settings.-prefix map', async () => {
    const user = userEvent.setup();
    const { fetcher } = fakeFetcher(
      resolver({
        onPutNaming: () => {
          throw new ApiRequestError(
            400,
            {
              message: 'config validation failed',
              errors: [
                {
                  field: 'settings.file_naming_template',
                  message: 'template must render a non-empty name',
                },
              ],
            },
            '/api/v1/config/naming',
          );
        },
      }),
    );
    renderWithProviders(<MediaManagement />, { fetcher });

    const field = await screen.findByTestId('template-field-file_naming_template');
    const input = within(field).getByRole('textbox');
    await user.clear(input);
    await user.type(input, '   ');
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    // The error lands on the offending field, not a bare form banner.
    await waitFor(() =>
      expect(within(field).getByRole('alert')).toHaveTextContent(
        'template must render a non-empty name',
      ),
    );
  });
});

describe('FRG-UI-012: per-series rename preview', () => {
  it('FRG-UI-012 — the preview lists old->new diffs and mutates nothing until confirm', async () => {
    const user = userEvent.setup();
    const { spy, fetcher } = fakeFetcher(resolver());
    renderWithProviders(<MediaManagement />, { fetcher });

    await user.selectOptions(
      await screen.findByLabelText('Series to preview renames for'),
      '7',
    );
    await user.click(screen.getByRole('button', { name: 'Preview Rename' }));

    const table = await screen.findByTestId('rename-preview-table');
    expect(within(table).getByText('wrong scan.cbz')).toBeInTheDocument();
    expect(
      within(table).getByText('Invincible 001 (2003) [__5__].cbz'),
    ).toBeInTheDocument();

    // No POST /rename has happened yet — the preview touched no disk.
    expect(
      spy.mock.calls.filter(([p, i]) => p === '/api/v1/rename' && i?.method === 'POST'),
    ).toHaveLength(0);

    await user.click(screen.getByTestId('rename-confirm'));

    // Confirm enqueues the rename-series command via POST /rename.
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(
        '/api/v1/rename',
        expect.objectContaining({ method: 'POST', body: { seriesId: 7 } }),
      ),
    );
    // The resulting command's progress surfaces via the command machinery.
    expect(await screen.findByTestId('rename-command-status')).toBeInTheDocument();
  });

  it('FRG-UI-012 — a series already matching the template shows nothing to rename', async () => {
    const user = userEvent.setup();
    const { fetcher } = fakeFetcher(resolver({ renameRows: () => [] }));
    renderWithProviders(<MediaManagement />, { fetcher });

    await user.selectOptions(
      await screen.findByLabelText('Series to preview renames for'),
      '7',
    );
    await user.click(screen.getByRole('button', { name: 'Preview Rename' }));

    expect(await screen.findByTestId('rename-no-changes')).toBeInTheDocument();
    // Nothing to confirm.
    expect(screen.getByTestId('rename-confirm')).toBeDisabled();
  });

  it('FRG-UI-012 — reopening the panel while a rename-series is still running keeps Confirm disabled', async () => {
    const user = userEvent.setup();
    // The panel is transient, so its own commandId is lost on close+reopen; the
    // server's command list still reports the in-flight rename for this series.
    const running = makeCommand({
      id: 77,
      name: 'rename-series',
      status: 'started',
      payload: { series_id: 7 },
    });
    const { spy, fetcher } = fakeFetcher(
      resolver({ commandList: () => [running], command: () => running }),
    );
    renderWithProviders(<MediaManagement />, { fetcher });

    await user.selectOptions(
      await screen.findByLabelText('Series to preview renames for'),
      '7',
    );
    await user.click(screen.getByRole('button', { name: 'Preview Rename' }));
    await screen.findByTestId('rename-preview-table');

    const confirm = screen.getByTestId('rename-confirm');
    await waitFor(() => expect(confirm).toBeDisabled());
    expect(confirm).toHaveTextContent('Renaming…');
    // The running command is reused, NOT duplicated — no fresh POST /rename.
    expect(
      spy.mock.calls.filter(([p, i]) => p === '/api/v1/rename' && i?.method === 'POST'),
    ).toHaveLength(0);
  });

  it('FRG-UI-012 — when the rename command completes the Confirm button stops saying "Renaming…"', async () => {
    const user = userEvent.setup();
    const { fetcher } = fakeFetcher(
      resolver({
        onPostRename: () =>
          makeCommand({ id: 55, name: 'rename-series', status: 'queued', payload: { series_id: 7 } }),
        command: () =>
          makeCommand({ id: 55, name: 'rename-series', status: 'completed', payload: { series_id: 7 } }),
      }),
    );
    renderWithProviders(<MediaManagement />, { fetcher });

    await user.selectOptions(
      await screen.findByLabelText('Series to preview renames for'),
      '7',
    );
    await user.click(screen.getByRole('button', { name: 'Preview Rename' }));
    await screen.findByTestId('rename-preview-table');
    await user.click(screen.getByTestId('rename-confirm'));

    // The watched command reaches a terminal status → the button reflects
    // completion instead of sticking on "Renaming…".
    await waitFor(() =>
      expect(screen.getByTestId('rename-command-status')).toHaveTextContent('completed'),
    );
    expect(screen.getByTestId('rename-confirm')).not.toHaveTextContent('Renaming…');
  });
});

describe('FRG-UI-012: the example is honest while the token vocabulary is unresolved', () => {
  it('FRG-UI-012 — a tokens fetch error shows "example unavailable", never empty-token garbage', async () => {
    const { fetcher } = fakeFetcher(
      resolver({
        onTokens: () => {
          throw new Error('tokens endpoint down');
        },
      }),
    );
    renderWithProviders(<MediaManagement />, { fetcher });

    const example = await screen.findByTestId('example-file_naming_template');
    await waitFor(() => expect(example).toHaveTextContent('example unavailable'));
    // The old bug rendered every unresolved token empty → "Example: ().cbz".
    expect(example).not.toHaveTextContent('().cbz');
  });

  it('FRG-UI-012 — while the token vocabulary is still loading the example shows a loading state', async () => {
    const { fetcher } = fakeFetcher(
      resolver({ onTokens: () => new Promise(() => {}) }),
    );
    renderWithProviders(<MediaManagement />, { fetcher });

    const example = await screen.findByTestId('example-file_naming_template');
    expect(example).toHaveTextContent('loading example…');
    expect(example).not.toHaveTextContent('().cbz');
  });
});

describe('FRG-UI-012: reset a template to its shipped default', () => {
  it('FRG-UI-012 — editing reveals "Reset to default"; clicking restores tokens.defaults', async () => {
    const user = userEvent.setup();
    const { fetcher } = fakeFetcher(resolver());
    renderWithProviders(<MediaManagement />, { fetcher });

    const field = await screen.findByTestId('template-field-file_naming_template');
    const input = within(field).getByRole('textbox');
    // Seeded exactly at the default → no reset affordance is offered.
    expect(
      within(field).queryByTestId('reset-default-file_naming_template'),
    ).toBeNull();

    await user.clear(input);
    await user.type(input, '{{Series Title}');
    const reset = within(field).getByTestId('reset-default-file_naming_template');
    await user.click(reset);

    // Restored from the endpoint's defaults contract, not a hardcoded string.
    expect(input).toHaveValue(TOKENS.defaults.file_naming_template);
  });
});
