import { useState, type FormEvent } from 'react';
import { Chip } from '../../components/Chip';
import { useLookup, useSuggest, SUGGEST_MIN_TERM_LENGTH } from '../../api/hooks';
import {
  lookupOutcomeNote,
  normalizeLookupTerm,
  OutcomeErrorText,
} from '../add/AddSeries';
import type { LookupCandidate, SuggestCandidate } from '../../api/types';
import styles from './sources.module.css';

/**
 * The shape the picker hands back — structurally satisfied by BOTH a full
 * `LookupCandidate` and a bounded `SuggestCandidate`, so a pick from the
 * debounced dropdown and a pick from the full search take the identical path
 * (the row decides match-vs-add from `have_it`).
 */
export type PickedCandidate = Pick<
  LookupCandidate,
  'cv_volume_id' | 'name' | 'have_it'
>;

/**
 * Seed term for a row's search (FRG-UI-039): the SERVER's stripped
 * series-shaped fold (`group_key`) when present — the same term the proposal
 * ranker searches with, so edition boilerplate ("Vol. 243", "Book One") never
 * rides into the seed and empties the suggest. Live-rig finding 2026-07-28: a
 * raw-title seed returned nothing until the operator hand-deleted the volume
 * ordinal on every single row. The client never re-implements the fold; the
 * raw-title trim is only the fallback for rows without a usable group_key.
 */
export function searchSeedTerm(humanName: string, groupKey?: string | null): string {
  const key = (groupKey ?? '').trim();
  if (key) return key;
  const stripped = humanName.replace(/\s*#\s*\d+[a-z]?\s*$/i, '').trim();
  return stripped || humanName.trim();
}

/** One candidate row inside the picker — the pick target for match-or-add. */
function CandidateButton({
  candidate,
  testId,
  busy,
  onPick,
}: {
  candidate: SuggestCandidate | LookupCandidate;
  testId: string;
  busy: boolean;
  onPick: () => void;
}) {
  return (
    <button
      type="button"
      className={styles.searchCandidate}
      data-testid={testId}
      data-have-it={candidate.have_it ? 'true' : 'false'}
      disabled={busy}
      onClick={onPick}
    >
      <span className={styles.searchCandidateMain}>
        <span className={styles.searchCandidateTitle}>
          {candidate.name ?? 'Unnamed volume'}
          {candidate.start_year !== null && (
            <span className={styles.searchCandidateYear}>
              {' '}
              ({candidate.start_year})
            </span>
          )}
        </span>
        <span className={styles.searchCandidateMeta}>
          {[
            candidate.publisher,
            candidate.count_of_issues !== null
              ? `${candidate.count_of_issues} issue${candidate.count_of_issues === 1 ? '' : 's'}`
              : null,
            'via ComicVine',
          ]
            .filter(Boolean)
            .join(' · ')}
        </span>
      </span>
      {/* The library overlay (FRG-UI-039): an already-owned volume is the
          cheapest possible answer — it links, it never creates. */}
      {candidate.have_it && (
        <Chip tone="accent" testId={`${testId}-have`}>
          In library
        </Chip>
      )}
    </button>
  );
}

/**
 * Per-row ComicVine search picker (FRG-UI-039) — the Add Series lookup surface
 * mounted inside one review row: the same debounced ≥3-char autosuggest
 * accelerator (`useSuggest`), the same authoritative full lookup (`useLookup`,
 * with the same pasted-URL/id normalization and same-term retry), the same
 * outcome-note classification (`lookupOutcomeNote` / `OutcomeErrorText`, so a
 * credential failure or a degraded/capped walk reads identically here and on
 * the add screen), the same publisher-ignore-list reveal, and the same
 * in-library marking. Picking hands the candidate up to the row, which matches
 * an owned volume and adds-and-matches an unowned one.
 *
 * This is the reason no review row is a dead end: it renders on every
 * reviewable row regardless of what the automatic proposal concluded.
 */
export function EntitlementSearch({
  entitlementId,
  seedTerm,
  busy,
  noteText,
  onPick,
  onCancel,
}: {
  entitlementId: number;
  seedTerm: string;
  busy: boolean;
  /** The automatic verdict shown BESIDE the search, never instead of it. */
  noteText: string;
  onPick: (candidate: PickedCandidate) => void;
  onCancel: () => void;
}) {
  const [input, setInput] = useState(seedTerm);
  const [term, setTerm] = useState('');
  const [showIgnored, setShowIgnored] = useState(false);
  const lookup = useLookup(term, showIgnored);
  const suggest = useSuggest(input);

  // An error must never leak stale candidates from a previous outcome: the
  // results and the note both derive from this one value.
  const results = lookup.isError ? undefined : lookup.data;
  const note = lookupOutcomeNote(lookup.isError, lookup.error, results, term);
  const hiddenByIgnore = results?.hidden_by_ignore_list ?? 0;

  // Suggest gating, identical in spirit to the add screen: the dropdown shows
  // only for a settled (debounced) term that still matches what is typed, and
  // retires the moment the authoritative lookup covers the same term.
  const suggestTerm = input.trim();
  const lookupSubmittedForInput = term.length > 0 && suggestTerm === term;
  const showSuggest =
    suggestTerm.length >= SUGGEST_MIN_TERM_LENGTH &&
    !lookupSubmittedForInput &&
    suggest.settledTerm === suggestTerm;
  const rawSuggestNote = showSuggest
    ? lookupOutcomeNote(suggest.isError, suggest.error, suggest.data, suggestTerm)
    : null;
  // Only the hard-failure tone nags from the accelerator; partial results still
  // render their candidates, and a clean empty is the full lookup's story.
  const suggestNote = rawSuggestNote?.tone === 'error' ? rawSuggestNote : null;
  const suggestCandidates =
    showSuggest && !suggest.isError ? (suggest.data?.records ?? []) : [];

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const next = normalizeLookupTerm(input);
    // A same-term re-submit after an error or a degraded/capped outcome must
    // retry for real; complete, uncapped lookups stay cached (rate-limited
    // upstream — FRG-META-016).
    const retryable =
      lookup.isError ||
      (lookup.data !== undefined &&
        (!lookup.data.complete || lookup.data.truncated));
    if (next === term && retryable) void lookup.refetch();
    if (next !== term) setShowIgnored(false);
    setTerm(next);
  };

  return (
    <div className={styles.rowSearch} data-testid={`row-search-${entitlementId}`}>
      <div className={styles.rowSearchHead}>
        <span className={styles.rowSearchNote} data-testid={`row-search-note-${entitlementId}`}>
          {noteText}
        </span>
        <button
          type="button"
          className={styles.mutedBtn}
          onClick={onCancel}
          data-testid={`row-search-cancel-${entitlementId}`}
        >
          Cancel
        </button>
      </div>

      <form className={styles.rowSearchForm} onSubmit={submit} role="search">
        <input
          className={styles.rowSearchInput}
          type="search"
          aria-label="Search ComicVine for this item"
          placeholder="Series name, or a ComicVine volume URL / 4050-XXXX id"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          data-testid={`row-search-input-${entitlementId}`}
        />
        <button type="submit" className={styles.linkBtn}>
          Search
        </button>
      </form>

      {lookup.isLoading && <p className={styles.searchState}>Searching ComicVine…</p>}
      {note?.tone === 'error' && (
        <p className={styles.searchError} role="alert">
          <OutcomeErrorText error={lookup.error} text={note.text} />
        </p>
      )}
      {note?.tone === 'status' && (
        <p className={styles.searchState} role="status">
          {note.text}
        </p>
      )}
      {note?.tone === 'plain' && <p className={styles.searchState}>{note.text}</p>}

      {hiddenByIgnore > 0 && !showIgnored && (
        <p className={styles.searchState} data-testid={`row-ignored-hidden-${entitlementId}`}>
          {hiddenByIgnore} result{hiddenByIgnore === 1 ? '' : 's'} hidden by your
          publisher ignore list —{' '}
          <button
            type="button"
            className={styles.linkBtn}
            onClick={() => setShowIgnored(true)}
          >
            Show
          </button>
        </p>
      )}

      {suggestNote && (
        <p className={styles.searchError} role="alert">
          <OutcomeErrorText error={suggest.error} text={suggestNote.text} />
        </p>
      )}

      {(suggestCandidates.length > 0 || (results?.records.length ?? 0) > 0) && (
        <div className={styles.searchResults}>
          {/* The full lookup, once submitted, is authoritative for its term —
              the accelerator's rows are suppressed so the two never stack. */}
          {(results && results.records.length > 0
            ? results.records
            : suggestCandidates
          ).map((candidate) => (
            <CandidateButton
              key={candidate.cv_volume_id}
              candidate={candidate}
              testId={`cand-${entitlementId}-${candidate.cv_volume_id}`}
              busy={busy}
              onPick={() => onPick(candidate)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
