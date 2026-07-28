import { describe, it, expect } from 'vitest';
import { normalizeReleaseResponse } from './hooks';
import { mockReleases } from '../test/mockData';

/*
 * FRG-UI-041 — the interactive-search response seam.
 *
 * The per-indexer outcomes are an ADDITIVE field (FRG-API-008): the UI must
 * render rows from a response that has no outcomes at all (a cached response
 * predating the field) and must present one canonical outcome shape whichever
 * spelling the resource uses.
 */
describe('FRG-UI-041: release response normalization', () => {
  it('FRG-UI-041 — a bare decision array yields the rows and no outcomes', () => {
    expect(normalizeReleaseResponse(mockReleases)).toEqual({
      decisions: mockReleases,
      indexers: [],
    });
  });

  it('FRG-UI-041 — an enveloped response without the outcomes field still yields its rows', () => {
    expect(normalizeReleaseResponse({ releases: mockReleases })).toEqual({
      decisions: mockReleases,
      indexers: [],
    });
    // Nothing usable at all degrades to empty, never a throw at the operator.
    expect(normalizeReleaseResponse(null)).toEqual({ decisions: [], indexers: [] });
    expect(normalizeReleaseResponse({})).toEqual({ decisions: [], indexers: [] });
  });

  it('FRG-UI-041 — outcome entries carry the resource vocabulary; an unknown state degrades to failed', () => {
    const { indexers } = normalizeReleaseResponse({
      releases: [],
      indexers: [
        // Field spellings verbatim from IndexerOutcomeResource, incl. the
        // candidate_count the strip does not render.
        { indexer_id: 1, name: 'DogNZB', outcome: 'searched', candidate_count: 12 },
        { indexer_id: 2, name: 'NZB.su', outcome: 'timed_out', budget_seconds: 20 },
        { indexer_id: 4, name: 'Sleeping', outcome: 'backing_off' },
        { indexer_id: 5, name: 'Broken', outcome: 'who-knows' },
      ],
    });

    expect(indexers).toEqual([
      { indexer_id: 1, name: 'DogNZB', outcome: 'searched', budget_seconds: null },
      { indexer_id: 2, name: 'NZB.su', outcome: 'timed_out', budget_seconds: 20 },
      { indexer_id: 4, name: 'Sleeping', outcome: 'backing_off', budget_seconds: null },
      // An unknown token is reported as a failure, never rendered raw.
      { indexer_id: 5, name: 'Broken', outcome: 'failed', budget_seconds: null },
    ]);
  });
});
