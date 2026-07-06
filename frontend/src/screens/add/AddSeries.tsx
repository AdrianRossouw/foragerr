import { useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Toolbar } from '../../components/Toolbar';
import { Poster } from '../../components/Poster';
import { SearchIcon, CloseIcon } from '../../components/icons';
import {
  useAddSeries,
  useFormatProfiles,
  useLookup,
  useRootFolders,
  useSuggest,
} from '../../api/hooks';
import { isComicVineAuthError } from '../../api/fetcher';
import type {
  LookupCandidate,
  LookupResponse,
  SuggestCandidate,
} from '../../api/types';
import { MONITOR_STRATEGIES } from '../../api/types';
import { formatBytes } from '../../lib/format';
import styles from './AddSeries.module.css';

/**
 * Add series (FRG-UI-005): ComicVine lookup (title text or a pasted CV
 * volume id/URL) -> candidate cards with plausibility annotations
 * (FRG-META-007 signals rendered, never hidden) -> add-options panel ->
 * POST /api/v1/series -> navigate to the new detail route carrying the queued
 * refresh command id so it renders live there.
 */

/**
 * Normalize a pasted ComicVine volume URL or "cv:4050-XXXX" idiom down to the
 * bare 4050-prefixed volume id; anything else passes through as a title term.
 */
export function normalizeLookupTerm(raw: string): string {
  const trimmed = raw.trim();
  const idMatch = trimmed.match(/(?:^cv:)?.*?(4050-\d+)/i);
  return idMatch ? idMatch[1] : trimmed;
}

/**
 * Classify the lookup outcome into the single note that renders (FRG-UI-005):
 * exactly one outcome state at a time, in precedence order — credential error
 * (structural, via the errors[] field discriminator) → generic error →
 * degraded walk that returned nothing (error styling, retry guidance) →
 * capped result (narrow the term; candidates still render) → incomplete
 * result (candidates still render) → complete-and-empty → candidates only.
 * Exported for reuse by every inline ComicVine lookup (FRG-UI-015 group
 * correction) so degraded/capped/credential outcomes render identically.
 */
export function lookupOutcomeNote(
  isError: boolean,
  error: unknown,
  data: LookupResponse | undefined,
  term: string,
): { tone: 'error' | 'status' | 'plain'; text: string } | null {
  if (isError) {
    return {
      tone: 'error',
      text: isComicVineAuthError(error)
        ? 'ComicVine API key missing or invalid — check Settings.'
        : 'ComicVine lookup failed. Try again in a moment.',
    };
  }
  if (!data) return null;
  if (!data.complete && data.records.length === 0) {
    return {
      tone: 'error',
      text: 'ComicVine lookup failed part-way and returned nothing — try again in a moment.',
    };
  }
  if (data.truncated) {
    return {
      tone: 'status',
      text: 'Too many results — ComicVine capped this search. Narrow the term.',
    };
  }
  if (!data.complete) {
    return {
      tone: 'status',
      text: 'Results may be incomplete — ComicVine did not return everything.',
    };
  }
  if (data.records.length === 0) {
    return { tone: 'plain', text: `No volumes found for “${term}”.` };
  }
  return null;
}

/**
 * Router navigation-state contract for arriving at Add Series with a
 * prefilled term (FRG-UI-005 / FRG-UI-019) — the header quick-search
 * fall-through (`HeaderQuickSearch`) navigates here with this shape.
 */
export interface AddSeriesNavigationState {
  prefillTerm?: string;
}

/**
 * The minimal shape `AddOptionsPanel`/`add()` need, satisfied structurally by
 * BOTH a full-lookup `LookupCandidate` and a bounded `SuggestCandidate`
 * (FRG-UI-005): selecting a suggestion opens the exact same add panel and
 * add path as selecting a full-lookup candidate, with no divergent branch.
 */
type AddableCandidate = Pick<LookupCandidate, 'cv_volume_id' | 'name' | 'have_it'>;

/** Monitor-strategy display labels, shared with the library-import batch panel. */
export const STRATEGY_LABELS: Record<string, string> = {
  all: 'All issues',
  none: 'None',
  future: 'Future issues',
  missing: 'Missing issues',
  existing: 'Existing issues',
  first: 'First issue',
};

function PlausibilityChips({ candidate }: { candidate: LookupCandidate }) {
  return (
    <span className={styles.chipRow}>
      {candidate.count_of_issues !== null && (
        <span className={styles.chip}>
          {candidate.count_of_issues} issue
          {candidate.count_of_issues === 1 ? '' : 's'}
        </span>
      )}
      <span className={styles.chip}>
        Name match {Math.round(candidate.name_similarity * 100)}%
      </span>
      {candidate.year_proximity !== null && (
        <span className={styles.chip}>
          {candidate.year_proximity === 0
            ? 'Year match'
            : `Year ±${candidate.year_proximity}`}
        </span>
      )}
      {candidate.target_issue_plausible !== null &&
        (candidate.target_issue_plausible ? (
          <span className={`${styles.chip} ${styles.chipGood}`}>
            Target issue plausible
          </span>
        ) : (
          <span className={`${styles.chip} ${styles.chipWarn}`}>
            Target issue unlikely
          </span>
        ))}
      {candidate.have_it && (
        <span className={`${styles.chip} ${styles.chipHave}`}>In library</span>
      )}
    </span>
  );
}

function AddOptionsPanel({
  candidate,
  busy,
  error,
  onAdd,
}: {
  candidate: AddableCandidate;
  busy: boolean;
  error: string | null;
  onAdd: (options: {
    rootFolderId: number;
    formatProfileId: number | null;
    monitorStrategy: string;
    searchOnAdd: boolean;
  }) => void;
}) {
  const rootFolders = useRootFolders();
  const formatProfiles = useFormatProfiles();
  // null = not chosen yet -> default to the first entry once the list loads.
  const [rootFolderId, setRootFolderId] = useState<number | null>(null);
  const [formatProfileId, setFormatProfileId] = useState<number | null>(null);
  const [monitorStrategy, setMonitorStrategy] = useState('all');
  const [searchOnAdd, setSearchOnAdd] = useState(false);

  const selectedRootFolderId = rootFolderId ?? rootFolders.data?.[0]?.id ?? null;
  const selectedProfileId =
    formatProfileId ?? formatProfiles.data?.[0]?.id ?? null;
  // No-roots state (FRG-UI-012 first-run scenario): a fresh install has no
  // registered root folder, so adding is impossible — point at the settings
  // section where one can actually be created instead of a dead-end select.
  const noRootFolders =
    rootFolders.data !== undefined && rootFolders.data.length === 0;

  return (
    <div className={styles.addPanel} data-testid="add-options-panel">
      {noRootFolders ? (
        <p className={styles.errorNote} role="alert" data-testid="add-no-roots">
          No root folders are registered, so the series has nowhere to live.
          Add your comics folder as a root folder in{' '}
          <Link to="/settings/media-management">Media Management settings</Link>{' '}
          first.
        </p>
      ) : (
        <label className={styles.formRow}>
          <span>Root Folder</span>
          <select
            aria-label="Root folder"
            value={selectedRootFolderId ?? ''}
            onChange={(e) => setRootFolderId(Number(e.target.value))}
          >
            {rootFolders.data?.map((folder) => (
              <option key={folder.id} value={folder.id}>
                {folder.path}
                {folder.free_space !== null &&
                  ` — ${formatBytes(folder.free_space)} free`}
              </option>
            ))}
          </select>
        </label>
      )}
      <label className={styles.formRow}>
        <span>Format Profile</span>
        <select
          aria-label="Format profile"
          value={selectedProfileId ?? ''}
          onChange={(e) => setFormatProfileId(Number(e.target.value))}
        >
          {formatProfiles.data?.map((profile) => (
            <option key={profile.id} value={profile.id}>
              {profile.name}
            </option>
          ))}
        </select>
      </label>
      <label className={styles.formRow}>
        <span>Monitor</span>
        <select
          aria-label="Monitor strategy"
          value={monitorStrategy}
          onChange={(e) => setMonitorStrategy(e.target.value)}
        >
          {MONITOR_STRATEGIES.map((s) => (
            <option key={s} value={s}>
              {STRATEGY_LABELS[s]}
            </option>
          ))}
        </select>
      </label>
      <label className={styles.checkboxRow}>
        <input
          type="checkbox"
          checked={searchOnAdd}
          onChange={(e) => setSearchOnAdd(e.target.checked)}
        />
        Start search for missing issues
      </label>
      {error && <p className={styles.errorNote}>{error}</p>}
      <button
        type="button"
        className={styles.addButton}
        data-testid="ft-add-confirm"
        disabled={busy || selectedRootFolderId === null}
        onClick={() => {
          if (selectedRootFolderId === null) return;
          onAdd({
            rootFolderId: selectedRootFolderId,
            formatProfileId: selectedProfileId,
            monitorStrategy,
            searchOnAdd,
          });
        }}
      >
        Add {candidate.name ?? 'series'}
      </button>
    </div>
  );
}

export function AddSeries() {
  const navigate = useNavigate();
  const location = useLocation();
  // Prefill from the header quick-search fall-through (FRG-UI-019 ->
  // FRG-UI-005): read once on mount so both the input AND the debounced
  // autosuggest below are seeded immediately, without an artificial delay.
  const prefillTerm =
    (location.state as AddSeriesNavigationState | null)?.prefillTerm ?? '';
  const [input, setInput] = useState(prefillTerm);
  const [term, setTerm] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedSuggestionId, setSelectedSuggestionId] = useState<
    number | null
  >(null);
  const lookup = useLookup(term);
  const suggest = useSuggest(input);
  const addSeries = useAddSeries();

  // A lookup error must never leak stale candidates from a previous outcome:
  // the results list and the outcome note both derive from this one value.
  const results = lookup.isError ? undefined : lookup.data;
  const note = lookupOutcomeNote(lookup.isError, lookup.error, results, term);

  // The autosuggest dropdown shows once the trimmed term clears the same
  // >=3-char threshold `useSuggest` gates on. It stays visible while ONE OF
  // ITS OWN candidates is selected (so that selection's inline add panel,
  // rendered inside this section below, remains on screen) but hides while a
  // FULL-LOOKUP candidate is selected instead, so the two add panels never
  // show at once.
  const suggestTerm = input.trim();
  const showSuggest = suggestTerm.length >= 3 && selectedId === null;
  // Reuses the full lookup's outcome classifier verbatim (isComicVineAuthError
  // under the hood) so a suggest credential failure renders the SAME
  // actionable Settings-guidance text, structurally discriminated — never by
  // sniffing message prose, and never dressed up as an empty dropdown.
  const suggestNote = showSuggest
    ? lookupOutcomeNote(suggest.isError, suggest.error, undefined, suggestTerm)
    : null;
  const suggestCandidates = suggest.isError ? [] : suggest.data?.records ?? [];

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSelectedId(null);
    setSelectedSuggestionId(null);
    const next = normalizeLookupTerm(input);
    // A same-term re-submit after an error or a degraded/capped outcome must
    // retry for real (FRG-UI-005): setting an identical term re-renders
    // nothing and never refetches, so refire explicitly. Complete, uncapped
    // lookups stay cached (staleTime Infinity in useLookup) — re-submitting
    // those is deliberately a no-op against the rate-limited upstream.
    const retryable =
      lookup.isError ||
      (lookup.data !== undefined &&
        (!lookup.data.complete || lookup.data.truncated));
    if (next === term && retryable) {
      void lookup.refetch();
    }
    setTerm(next);
  };

  const add = (
    candidate: AddableCandidate,
    options: {
      rootFolderId: number;
      formatProfileId: number | null;
      monitorStrategy: string;
      searchOnAdd: boolean;
    },
  ) => {
    addSeries.mutate(
      {
        cv_volume_id: candidate.cv_volume_id,
        root_folder_id: options.rootFolderId,
        format_profile_id: options.formatProfileId,
        monitor_strategy: options.monitorStrategy,
        monitor_new_items: 'all',
        search_on_add: options.searchOnAdd,
      },
      {
        onSuccess: (created) =>
          navigate(`/series/${created.id}`, {
            state: { refreshCommandId: created.refresh_command_id },
          }),
      },
    );
  };

  return (
    <>
      <Toolbar title="Add New" />
      <div className={styles.content}>
        <form className={styles.searchForm} onSubmit={submit} role="search">
          <span className={styles.searchIcon} aria-hidden>
            <SearchIcon size={16} />
          </span>
          <input
            className={styles.searchInput}
            type="search"
            aria-label="Search ComicVine"
            placeholder="eg. Saga, or paste a ComicVine volume URL / 4050-XXXX id"
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
          {input && (
            <button
              type="button"
              className={styles.clearButton}
              aria-label="Clear search"
              onClick={() => setInput('')}
            >
              <CloseIcon size={14} />
            </button>
          )}
          <button type="submit" className={styles.submitButton}>
            Search
          </button>
        </form>

        {showSuggest && (
          <div className={styles.suggestDropdown} data-testid="suggest-dropdown">
            {suggestNote?.tone === 'error' && (
              <p className={styles.errorNote} role="alert">
                {suggestNote.text}
              </p>
            )}
            {!suggestNote &&
              suggestCandidates.map((candidate: SuggestCandidate) => (
                <div
                  key={candidate.cv_volume_id}
                  className={styles.candidateCard}
                  data-testid={`suggest-${candidate.cv_volume_id}`}
                >
                  <button
                    type="button"
                    className={styles.candidateBody}
                    aria-label={`Select suggestion ${candidate.name ?? 'unnamed volume'}`}
                    disabled={candidate.have_it}
                    onClick={() =>
                      setSelectedSuggestionId(
                        selectedSuggestionId === candidate.cv_volume_id
                          ? null
                          : candidate.cv_volume_id,
                      )
                    }
                  >
                    <Poster
                      initial={(candidate.name ?? '?').charAt(0)}
                      src={candidate.image_url}
                      alt={`${candidate.name ?? 'volume'} cover`}
                      frameClassName={styles.posterFrame}
                      fallbackClassName={styles.posterFallback}
                      lazy
                    />
                    <span className={styles.candidateInfo}>
                      <span className={styles.candidateTitle}>
                        {candidate.name ?? 'Unnamed volume'}
                        {candidate.start_year !== null && (
                          <span className={styles.candidateYear}>
                            {' '}
                            ({candidate.start_year})
                          </span>
                        )}
                      </span>
                      {candidate.publisher && (
                        <span className={styles.publisher}>{candidate.publisher}</span>
                      )}
                      <span className={styles.chipRow}>
                        {candidate.count_of_issues !== null && (
                          <span className={styles.chip}>
                            {candidate.count_of_issues} issue
                            {candidate.count_of_issues === 1 ? '' : 's'}
                          </span>
                        )}
                        {candidate.have_it && (
                          <span className={`${styles.chip} ${styles.chipHave}`}>
                            In library
                          </span>
                        )}
                      </span>
                    </span>
                  </button>
                  {selectedSuggestionId === candidate.cv_volume_id &&
                    !candidate.have_it && (
                      <AddOptionsPanel
                        candidate={candidate}
                        busy={addSeries.isPending}
                        error={addSeries.error ? addSeries.error.message : null}
                        onAdd={(options) => add(candidate, options)}
                      />
                    )}
                </div>
              ))}
          </div>
        )}

        {lookup.isLoading && <p className={styles.stateNote}>Searching ComicVine…</p>}
        {note?.tone === 'error' && (
          <p className={styles.errorNote} role="alert">
            {note.text}
          </p>
        )}
        {note?.tone === 'status' && (
          <p className={styles.stateNote} role="status">
            {note.text}
          </p>
        )}
        {note?.tone === 'plain' && <p className={styles.stateNote}>{note.text}</p>}

        <div className={styles.results}>
          {results?.records.map((candidate) => (
            <div
              key={candidate.cv_volume_id}
              className={styles.candidateCard}
              data-testid={`candidate-${candidate.cv_volume_id}`}
            >
              <button
                type="button"
                className={styles.candidateBody}
                aria-label={`Select ${candidate.name ?? 'unnamed volume'}`}
                disabled={candidate.have_it}
                onClick={() => {
                  setSelectedSuggestionId(null);
                  setSelectedId(
                    selectedId === candidate.cv_volume_id
                      ? null
                      : candidate.cv_volume_id,
                  );
                }}
              >
                <Poster
                  initial={(candidate.name ?? '?').charAt(0)}
                  src={candidate.image_url}
                  alt={`${candidate.name ?? 'volume'} cover`}
                  frameClassName={styles.posterFrame}
                  fallbackClassName={styles.posterFallback}
                  lazy
                />
                <span className={styles.candidateInfo}>
                  <span className={styles.candidateTitle}>
                    {candidate.name ?? 'Unnamed volume'}
                    {candidate.start_year !== null && (
                      <span className={styles.candidateYear}>
                        {' '}
                        ({candidate.start_year})
                      </span>
                    )}
                  </span>
                  {candidate.publisher && (
                    <span className={styles.publisher}>{candidate.publisher}</span>
                  )}
                  <PlausibilityChips candidate={candidate} />
                </span>
              </button>
              {selectedId === candidate.cv_volume_id && !candidate.have_it && (
                <AddOptionsPanel
                  candidate={candidate}
                  busy={addSeries.isPending}
                  error={addSeries.error ? addSeries.error.message : null}
                  onAdd={(options) => add(candidate, options)}
                />
              )}
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
