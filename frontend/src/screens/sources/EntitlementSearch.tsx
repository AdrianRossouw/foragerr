import { useState, type FormEvent } from 'react';
import { Chip } from '../../components/Chip';
import {
  useLookup,
  useLookupVolume,
  useSuggest,
  SUGGEST_MIN_TERM_LENGTH,
} from '../../api/hooks';
import { isComicVineAuthError } from '../../api/fetcher';
import {
  lookupOutcomeNote,
  normalizeLookupTerm,
  OutcomeErrorText,
  parseVolumeId,
  VOLUME_ID_PATTERN,
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
      {/* A title-cue hint (FRG-UI-039 / design D6), never a gate or a
          re-rank: ComicVine has no booktype field, so this reads a
          collected-edition volume from the SAME title heuristic the
          library's own booktype badge uses — soft wording on purpose. */}
      {candidate.collected_cues && (
        <Chip
          tone="muted"
          testId={`${testId}-collected`}
          title="Collected-edition title cues — a heuristic, not a confirmed book type"
        >
          Collected-edition cues
        </Chip>
      )}
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
  instanceId,
  seedTerm,
  busy,
  noteText,
  onPick,
  onCancel,
}: {
  /**
   * DOM-id namespace for this picker instance (testids, ARIA). A single row
   * passes its entitlement id; the group header (FRG-UI-043) passes a
   * group-scoped string — the picker itself is identical either way, it only
   * differs in the id space it stamps and the `onPick` the parent supplies.
   */
  instanceId: string | number;
  seedTerm: string;
  busy: boolean;
  /** The automatic verdict shown BESIDE the search, never instead of it. */
  noteText: string;
  onPick: (candidate: PickedCandidate) => void;
  onCancel: () => void;
}) {
  const [input, setInput] = useState(seedTerm);
  const [term, setTerm] = useState('');
  // A resolved-by-id volume (FRG-UI-039 / FRG-API-026), mutually exclusive
  // with `term`: submitting an id clears `term` (so the name lookup stays
  // disabled and fires no request), submitting a name clears this.
  const [volumeId, setVolumeId] = useState<number | null>(null);
  const [showIgnored, setShowIgnored] = useState(false);
  const lookup = useLookup(term, showIgnored);
  const volume = useLookupVolume(volumeId);
  // A pasted id/URL is recognizable BEFORE submit — the debounced accelerator
  // must never fire a name search for it either (design D6: never a name
  // search for an id, not even the passive one).
  const isIdInput = VOLUME_ID_PATTERN.test(normalizeLookupTerm(input));
  const suggest = useSuggest(isIdInput ? '' : input);

  // An error must never leak stale candidates from a previous outcome: the
  // results and the note both derive from this one value.
  const results = lookup.isError ? undefined : lookup.data;
  const note = lookupOutcomeNote(lookup.isError, lookup.error, results, term);
  const hiddenByIgnore = results?.hidden_by_ignore_list ?? 0;

  // The id path's own outcome (FRG-UI-039): a resolved volume renders through
  // the SAME candidate list below; an unknown id or an upstream failure
  // renders an honest note INSTEAD of the empty name-search results the
  // picker used to submit for a pasted id. Credential failures reuse the
  // structural discriminator (never message-sniffed) so the Settings link
  // reads identically everywhere this classifier is used.
  const volumeCandidate =
    volumeId !== null && !volume.isError ? volume.data : undefined;
  const volumeAuthError = volumeId !== null && isComicVineAuthError(volume.error);
  const volumeNote: { tone: 'error' | 'plain'; text: string } | null =
    volumeId === null || !volume.isError
      ? null
      : volumeAuthError
        ? { tone: 'error', text: 'ComicVine API key missing or invalid — check Settings.' }
        : { tone: 'plain', text: 'No ComicVine volume matches that id.' };

  // Suggest gating, identical in spirit to the add screen: the dropdown shows
  // only for a settled (debounced) term that still matches what is typed, and
  // retires the moment the authoritative lookup (or an id resolution) covers
  // the current input.
  const suggestTerm = input.trim();
  const lookupSubmittedForInput = term.length > 0 && suggestTerm === term;
  const showSuggest =
    !isIdInput &&
    volumeId === null &&
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
    if (VOLUME_ID_PATTERN.test(next)) {
      // The id path (FRG-API-026): route straight to the volume-id lookup
      // instead of the name search this term would otherwise become — the
      // exact dead end the picker used to advertise and never honor.
      setVolumeId(parseVolumeId(next));
      setTerm('');
      setShowIgnored(false);
      return;
    }
    setVolumeId(null);
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
    <div className={styles.rowSearch} data-testid={`row-search-${instanceId}`}>
      <div className={styles.rowSearchHead}>
        <span className={styles.rowSearchNote} data-testid={`row-search-note-${instanceId}`}>
          {noteText}
        </span>
        <button
          type="button"
          className={styles.mutedBtn}
          onClick={onCancel}
          data-testid={`row-search-cancel-${instanceId}`}
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
          onChange={(e) => {
            const next = e.target.value;
            setInput(next);
            // A resolved volume is the answer to the id that produced it. The
            // moment the box stops naming that id, the resolved candidate is
            // stale — drop it, which also re-enables the passive suggest (it is
            // gated on `volumeId === null`). Without this the picker sat on one
            // volume while the operator typed a series name at it, exactly the
            // dead end the id path was added to remove.
            if (
              volumeId !== null &&
              !VOLUME_ID_PATTERN.test(normalizeLookupTerm(next))
            ) {
              setVolumeId(null);
            }
          }}
          data-testid={`row-search-input-${instanceId}`}
        />
        <button type="submit" className={styles.linkBtn}>
          Search
        </button>
      </form>

      {volumeId !== null && volume.isLoading && (
        <p className={styles.searchState} data-testid={`row-search-volume-loading-${instanceId}`}>
          Looking up that volume…
        </p>
      )}
      {volumeNote?.tone === 'error' && (
        <p className={styles.searchError} role="alert">
          <OutcomeErrorText error={volume.error} text={volumeNote.text} />
        </p>
      )}
      {volumeNote?.tone === 'plain' && (
        <p className={styles.searchState} data-testid={`row-search-volume-note-${instanceId}`}>
          {volumeNote.text}
        </p>
      )}

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
        <p className={styles.searchState} data-testid={`row-ignored-hidden-${instanceId}`}>
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

      {(volumeCandidate ||
        suggestCandidates.length > 0 ||
        (results?.records.length ?? 0) > 0) && (
        <div className={styles.searchResults}>
          {volumeCandidate ? (
            // The id path resolves to exactly ONE volume — rendered through
            // the SAME CandidateButton/onPick path as a name search, so
            // in-library marking and add-and-match behave identically
            // (design D6).
            <CandidateButton
              key={volumeCandidate.cv_volume_id}
              candidate={volumeCandidate}
              testId={`cand-${instanceId}-${volumeCandidate.cv_volume_id}`}
              busy={busy}
              onPick={() => onPick(volumeCandidate)}
            />
          ) : (
            // The full lookup, once submitted, is authoritative for its term —
            // the accelerator's rows are suppressed so the two never stack.
            (results && results.records.length > 0
              ? results.records
              : suggestCandidates
            ).map((candidate) => (
              <CandidateButton
                key={candidate.cv_volume_id}
                candidate={candidate}
                testId={`cand-${instanceId}-${candidate.cv_volume_id}`}
                busy={busy}
                onPick={() => onPick(candidate)}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}
