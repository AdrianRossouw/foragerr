import { describe, it, expect } from 'vitest';
import { renderExample, renderTemplate, type TokenAliases } from './renderExample';

/*
 * FRG-UI-012 — the client-side live-example render mirror must MATCH backend
 * semantics for the default tokens (design decision 11, delta-spec scenario 5).
 *
 * Every EXPECT below is a fixture COPIED VERBATIM from the backend's own
 * `foragerr.naming` output (captured by running render_filename / render on the
 * same fields + templates); if the TS mirror drifts from the Python engine for
 * these default rules — padding, optional-group dropping, token-name case, the
 * illegal-char + whitespace file policy — these tests fail.
 */

// The token vocabulary is supplied by the backend (GET /config/naming/tokens),
// never hardcoded in production code — here it is inlined only as test input.
const ALIASES: TokenAliases = {
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
};

const FILE_TEMPLATE = '{Series Title} {Issue Number:000} ({Year}) [__{IssueId}__]';
const FOLDER_TEMPLATE = '{Series Title} ({Year})';

const file = (tpl: string, fields: Record<string, string | null>, replaceIllegal = true) =>
  renderExample(tpl, fields, ALIASES, { isFile: true, replaceIllegal, ext: '.cbz' });

const folder = (tpl: string, fields: Record<string, string | null>) =>
  renderExample(tpl, fields, ALIASES, { isFile: false });

describe('FRG-UI-012: live-example render mirror matches backend naming semantics', () => {
  it('FRG-UI-012 — full default file template renders identically to the backend', () => {
    const fields = {
      series_title: 'Saga', issue: '5', year: '2012', issue_id: '12345',
      volume: '1', publisher: 'Image', issue_title: 'Chapter Five', release_group: 'DIGITAL',
    };
    // backend render_filename(...) => 'Saga 005 (2012) [__12345__].cbz'
    expect(file(FILE_TEMPLATE, fields)).toBe('Saga 005 (2012) [__12345__].cbz');
  });

  it('FRG-UI-012 — an empty optional group (missing IssueId) is dropped, like the backend', () => {
    const fields = { series_title: 'Saga', issue: '5', year: '2012', issue_id: null };
    // backend => 'Saga 005 (2012).cbz' (the [__{IssueId}__] span drops out)
    expect(file(FILE_TEMPLATE, fields)).toBe('Saga 005 (2012).cbz');
  });

  it('FRG-UI-012 — a non-empty optional group is kept, like the backend', () => {
    const tpl = '{Series Title} {Issue Number:000} ({Year}) [{Release Group}]';
    // backend => 'Batman 001 (2011) [DiG].cbz'
    expect(file(tpl, { series_title: 'Batman', issue: '1', year: '2011', release_group: 'DiG' }))
      .toBe('Batman 001 (2011) [DiG].cbz');
    // backend, release group absent => 'Batman 001 (2011).cbz'
    expect(file(tpl, { series_title: 'Batman', issue: '1', year: '2011', release_group: null }))
      .toBe('Batman 001 (2011).cbz');
  });

  it('FRG-UI-012 — {Issue Number:000} zero-pads decimal-safely, like the backend', () => {
    // backend, issue '5.5' => 'Saga 005.5 (2012) [__12345__].cbz'
    expect(file(FILE_TEMPLATE, { series_title: 'Saga', issue: '5.5', year: '2012', issue_id: '12345' }))
      .toBe('Saga 005.5 (2012) [__12345__].cbz');
  });

  it('FRG-UI-012 — token-name case controls output case, like the backend', () => {
    // backend, '{series title} {ISSUE NUMBER:000}' => 'saga 005.cbz'
    expect(file('{series title} {ISSUE NUMBER:000}', { series_title: 'Saga', issue: '5', year: '2012' }))
      .toBe('saga 005.cbz');
  });

  it('FRG-UI-012 — the illegal-character policy matches the backend when enabled', () => {
    // backend, replace_illegal=True => 'Foo Bar Baz.cbz'
    expect(file('{Series Title}', { series_title: 'Foo/Bar: Baz' }, true)).toBe('Foo Bar Baz.cbz');
    // backend, replace_illegal=False => 'Foo/Bar: Baz.cbz'
    expect(file('{Series Title}', { series_title: 'Foo/Bar: Baz' }, false)).toBe('Foo/Bar: Baz.cbz');
  });

  it('FRG-UI-012 — the folder template renders identically to the backend', () => {
    // backend render(...) => 'Saga (2012)'
    expect(renderTemplate(FOLDER_TEMPLATE, { series_title: 'Saga', year: '2012' }, ALIASES))
      .toBe('Saga (2012)');
  });
});

describe('FRG-UI-012: folder example mirrors render_folder_segments + safe_path_component', () => {
  // Every EXPECT is copied verbatim from the real engine:
  //   '/'.join(safe_path_component(s)
  //            for s in render_folder_segments(RenameFields(**kw), template=tpl))
  it('FRG-UI-012 — the default folder template matches the backend', () => {
    // backend => 'Saga (2012)'
    expect(folder(FOLDER_TEMPLATE, { series_title: 'Saga', year: '2012' })).toBe('Saga (2012)');
  });

  it('FRG-UI-012 — a multi-segment folder template splits on "/" like the backend', () => {
    // backend => 'Image/Saga (2012)'
    expect(
      folder('{Publisher}/{Series Title} ({Year})', {
        series_title: 'Saga',
        year: '2012',
        publisher: 'Image',
      }),
    ).toBe('Image/Saga (2012)');
  });

  it('FRG-UI-012 — folder sanitization keeps ":" and only splits real separators (NOT the file policy)', () => {
    // backend => 'Foo/Bar: Baz' — the "/" in the title becomes a new segment
    // boundary, but ":" survives (safe_path_component, not the file illegal set).
    expect(folder('{Series Title}', { series_title: 'Foo/Bar: Baz' })).toBe('Foo/Bar: Baz');
  });

  it('FRG-UI-012 — an empty leading segment is dropped, like the backend', () => {
    // backend, publisher absent => 'Batman' (the empty '' segment drops out)
    expect(folder('{Publisher}/{Series Title}', { series_title: 'Batman', publisher: null }))
      .toBe('Batman');
  });

  it('FRG-UI-012 — an empty {Year} in literal parens is kept, like the backend', () => {
    // backend, year absent => 'Saga ()' (parens are literal, not an [optional] group)
    expect(folder(FOLDER_TEMPLATE, { series_title: 'Saga', year: null })).toBe('Saga ()');
  });

  it('FRG-UI-012 — a reserved device-name segment is de-reserved, like the backend', () => {
    // backend => '_CON'
    expect(folder('{Series Title}', { series_title: 'CON' })).toBe('_CON');
  });

  it('FRG-UI-012 — a trailing dot is stripped PER SEGMENT, not by the file policy', () => {
    // backend, template '{Series Title}.' => 'Trailing'
    expect(folder('{Series Title}.', { series_title: 'Trailing' })).toBe('Trailing');
  });
});
