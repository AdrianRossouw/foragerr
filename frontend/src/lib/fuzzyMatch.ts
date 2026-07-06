import type { SeriesResource } from '../api/types';

/*
 * In-repo fuzzy matcher (FRG-UI-019) backing the header quick-search. This is
 * deliberately NOT a library dependency — adding one would trigger a SOUP
 * register delta (m2-search-autosuggest design decision #6); a small
 * casefolded string-tier scan over the already-cached series index is cheap
 * enough at single-user library scale and needs no dependency at all.
 */

export type MatchTier = 'exact' | 'prefix' | 'word-boundary' | 'subsequence';

const TIER_RANK: Record<MatchTier, number> = {
  exact: 0,
  prefix: 1,
  'word-boundary': 2,
  subsequence: 3,
};

function normalize(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, ' ');
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** True when every character of `needle` appears in `haystack`, in order. */
function isSubsequence(needle: string, haystack: string): boolean {
  let cursor = 0;
  for (const char of haystack) {
    if (cursor < needle.length && char === needle[cursor]) cursor += 1;
  }
  return cursor === needle.length;
}

/**
 * Classifies how `term` matches `candidate` (casefolded, whitespace-
 * normalised), or returns null when it does not match at all. Precedence:
 * exact > prefix > word-boundary (term begins right after a non-alphanumeric
 * boundary or the string start, e.g. "swamp" in "Saga of the Swamp Thing") >
 * subsequence (every character of term appears in order, not necessarily
 * contiguously).
 */
export function matchTier(term: string, candidate: string): MatchTier | null {
  const t = normalize(term);
  const c = normalize(candidate);
  if (!t) return null;
  if (c === t) return 'exact';
  if (c.startsWith(t)) return 'prefix';
  if (new RegExp(`(^|[^a-z0-9])${escapeRegExp(t)}`, 'i').test(c)) {
    return 'word-boundary';
  }
  if (isSubsequence(t, c)) return 'subsequence';
  return null;
}

export interface SeriesMatch {
  series: SeriesResource;
  tier: MatchTier;
}

/**
 * Ranks the cached local library against `term` over BOTH title and aliases
 * (FRG-UI-019): a series' BEST tier across its title/alias set wins one entry
 * (never a duplicate row per alias), ties broken alphabetically by
 * sort_title. Non-matching series are omitted entirely, not merely ranked
 * last. An empty/blank term matches nothing (there is nothing to rank).
 */
export function matchSeries(
  term: string,
  series: readonly SeriesResource[],
): SeriesMatch[] {
  const trimmed = term.trim();
  if (!trimmed) return [];

  const matches: SeriesMatch[] = [];
  for (const item of series) {
    const names = [item.title, ...item.aliases];
    let best: MatchTier | null = null;
    for (const name of names) {
      const tier = matchTier(trimmed, name);
      if (tier && (best === null || TIER_RANK[tier] < TIER_RANK[best])) {
        best = tier;
        if (best === 'exact') break;
      }
    }
    if (best) matches.push({ series: item, tier: best });
  }

  matches.sort((a, b) => {
    const diff = TIER_RANK[a.tier] - TIER_RANK[b.tier];
    return diff !== 0 ? diff : a.series.sort_title.localeCompare(b.series.sort_title);
  });
  return matches;
}
