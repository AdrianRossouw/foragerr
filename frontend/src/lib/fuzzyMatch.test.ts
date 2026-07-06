import { describe, it, expect } from 'vitest';
import { matchTier, matchSeries } from './fuzzyMatch';
import { makeSeriesResource } from '../test/mockData';

/**
 * FRG-UI-019 — the in-repo fuzzy matcher behind the header quick-search:
 * casefolded exact/prefix/word-boundary/subsequence tiers, ranked in that
 * precedence, over BOTH a series' title and its aliases.
 */
describe('FRG-UI-019: fuzzy matcher', () => {
  it('FRG-UI-019 — classifies exact, prefix, word-boundary and subsequence tiers, casefolded', () => {
    expect(matchTier('saga', 'Saga')).toBe('exact');
    expect(matchTier('SAGA', 'saga')).toBe('exact');
    expect(matchTier('sag', 'Saga')).toBe('prefix');
    expect(matchTier('swamp', 'Saga of the Swamp Thing')).toBe('word-boundary');
    expect(matchTier('swmp', 'Saga of the Swamp Thing')).toBe('subsequence');
    expect(matchTier('xyz', 'Saga')).toBeNull();
    expect(matchTier('', 'Saga')).toBeNull();
  });

  it('FRG-UI-019 — matches over title AND aliases; an alias-only hit still surfaces the series', () => {
    const saga = makeSeriesResource({ id: 1, title: 'Saga', aliases: [] });
    const invincible = makeSeriesResource({
      id: 2,
      title: 'Invincible',
      aliases: ['The Invincible Man'],
    });

    const byTitle = matchSeries('SAGA', [saga, invincible]);
    expect(byTitle.map((m) => m.series.id)).toEqual([1]);
    expect(byTitle[0].tier).toBe('exact');

    const byAlias = matchSeries('invincible man', [saga, invincible]);
    expect(byAlias.map((m) => m.series.id)).toEqual([2]);
  });

  it('FRG-UI-019 — ranks exact/prefix ahead of word-boundary/subsequence across a mixed set', () => {
    const exact = makeSeriesResource({ id: 1, title: 'Bone', sort_title: 'bone' });
    const prefixHit = makeSeriesResource({
      id: 2,
      title: 'Bonecrusher',
      sort_title: 'bonecrusher',
    });
    const subsequenceHit = makeSeriesResource({
      id: 3,
      title: 'Big Old Nine Empires',
      sort_title: 'big old nine empires',
    });

    const results = matchSeries('bone', [subsequenceHit, prefixHit, exact]);
    expect(results.map((m) => m.series.id)).toEqual([1, 2, 3]);
    expect(results.map((m) => m.tier)).toEqual(['exact', 'prefix', 'subsequence']);
  });

  it('FRG-UI-019 — a blank term matches nothing, and non-matching series are omitted (not ranked last)', () => {
    const saga = makeSeriesResource({ id: 1, title: 'Saga' });
    const bone = makeSeriesResource({ id: 2, title: 'Bone' });
    expect(matchSeries('   ', [saga, bone])).toEqual([]);
    expect(matchSeries('zzz', [saga, bone])).toEqual([]);
  });
});
