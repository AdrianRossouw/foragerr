import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Toolbar } from '../../components/Toolbar';
import { Poster } from '../../components/Poster';
import { Chip } from '../../components/Chip';
import {
  SegmentedControl,
  type SegmentOption,
} from '../../components/SegmentedControl';
import { SearchIcon, CloseIcon, CheckIcon, PlusIcon } from '../../components/icons';
import {
  useAddSeries,
  useFormatProfiles,
  useLookup,
  useRootFolders,
  useSuggest,
} from '../../api/hooks';
import { isComicVineAuthError } from '../../api/fetcher';
import type {
  AddSeriesNavigationState,
  LookupCandidate,
  SeriesCreatePayload,
} from '../../api/types';
import { MONITOR_STRATEGIES } from '../../api/types';
import { publisherTint } from '../../theme/palettes';
import { formatBytes } from '../../lib/format';
import styles from './AddSeries.module.css';

/**
 * Add series (FRG-UI-005): ComicVine lookup (title text or a pasted CV
 * volume id/URL) -> expandable result cards per the M4 design handoff (cover,
 * name, year, publisher, issue count, deck, "In library" badge), rendered in
 * the API's relevance order (FRG-META-015) with no client-side reordering ->
 * inline add-config panel (root folder, format profile, monitor segmented,
 * collect-as segmented, search-on-add) -> POST /api/v1/series -> navigate to
 * the new detail route carrying the queued refresh command id so it renders
 * live there.
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
 * Defensive display strip of a ComicVine deck/description (FRG-UI-005): CV
 * deck text is user-editable wiki content (sanitized server-side, but treated
 * as untrusted here too — FRG-META-014). Reduce any residual markup to its
 * text by dropping tags and collapsing whitespace; the result is rendered as
 * React text (auto-escaped), never as HTML. Empty/whitespace-only decks become
 * `''` so the card can drop the deck row entirely.
 */
export function stripHtml(raw: string): string {
  return raw
    .replace(/<[^>]*>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
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
  // Structural subset shared by LookupResponse and SuggestResponse (the latter
  // has no `truncated`, so it is optional) — the classifier reads only these.
  data:
    | { records: readonly unknown[]; complete: boolean; truncated?: boolean }
    | undefined,
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
 * Render an error-tone outcome note's text (FRG-UI-020), upgrading the
 * credential-failure case into a link to the Settings -> General ComicVine
 * section so "check Settings" routes somewhere real. Classification reuses
 * the SAME structural discriminator `lookupOutcomeNote` used to pick the
 * message (`isComicVineAuthError`, never message prose) — this is layered on
 * top of its precedence logic as a rendering-only concern, not a change to
 * which outcome wins. Exported so `LibraryImport`'s inline `GroupLookup` —
 * which already reuses `lookupOutcomeNote` wholesale — renders the identical
 * credential-error link rather than a parallel copy.
 */
export function OutcomeErrorText({
  error,
  text,
}: {
  error: unknown;
  text: string;
}) {
  if (isComicVineAuthError(error)) {
    return (
      <>
        ComicVine API key missing or invalid —{' '}
        <Link to="/settings/general">check Settings</Link>.
      </>
    );
  }
  return <>{text}</>;
}

/**
 * The minimal shape `AddOptionsPanel`/`add()` need, satisfied structurally by
 * BOTH a full-lookup `LookupCandidate` and a bounded `SuggestCandidate`
 * (FRG-UI-005): selecting a suggestion opens the exact same add panel and
 * add path as selecting a full-lookup candidate, with no divergent branch.
 */
type AddableCandidate = Pick<LookupCandidate, 'cv_volume_id' | 'name' | 'have_it'>;

/**
 * The fields the shared result card renders (FRG-UI-005). Structurally
 * satisfied by BOTH `LookupCandidate` and `SuggestCandidate` so the full
 * lookup and the suggest dropdown render identical cards; `description` is
 * optional on both (a suggest candidate may omit it — the deck row is then
 * simply absent).
 */
type CardCandidate = Pick<
  LookupCandidate,
  | 'cv_volume_id'
  | 'name'
  | 'publisher'
  | 'start_year'
  | 'image_url'
  | 'have_it'
  | 'count_of_issues'
  | 'description'
  | 'ignored'
>;

/** Monitor-strategy display labels, shared with the library-import batch panel. */
export const STRATEGY_LABELS: Record<string, string> = {
  all: 'All issues',
  none: 'None',
  future: 'Future issues',
  missing: 'Missing issues',
  existing: 'Existing issues',
  first: 'First issue',
};

/**
 * "Collect as" control state (FRG-UI-005 / FRG-SER-018). `''` is the default
 * untouched state — the add request then carries NO booktype and the backend
 * derives it from title cues as before. `single`/`collected` map to the
 * explicit locked book-type sent on add.
 */
type CollectAs = '' | 'single' | 'collected';

/** The add-time booktype each explicit collect-as choice sends (design decision 3). */
const COLLECT_AS_BOOKTYPE: Record<Exclude<CollectAs, ''>, string> = {
  single: 'none',
  collected: 'tpb',
};

const COLLECT_AS_OPTIONS: readonly SegmentOption<CollectAs>[] = [
  { value: 'single', label: 'Single Issues', testId: 'collect-as-single' },
  { value: 'collected', label: 'Collected Editions', testId: 'collect-as-collected' },
];

/** Add-options the panel emits on confirm; `booktype` omitted = untouched. */
export interface AddOptions {
  rootFolderId: number;
  formatProfileId: number | null;
  monitorStrategy: string;
  searchOnAdd: boolean;
  booktype?: string;
}

/**
 * One ComicVine candidate card (FRG-UI-005) — the shared visual shell used by
 * BOTH the suggest dropdown and the full-lookup results so the two render
 * identically per the design handoff: cover (publisher-tinted placeholder),
 * name + year, an "In library" badge when already owned, a
 * publisher · issue-count · via-ComicVine meta line, and a 2-line deck. The
 * whole face is a toggle; `panel` is the add-options panel, mounted inline
 * only while this card is the selected one and the volume is not already owned
 * (an owned volume's card is inert — nothing to add). The `deck` is stripped
 * of residual markup before it reaches here.
 */
function CandidateCard({
  candidate,
  testId,
  selectLabel,
  selected,
  onToggle,
  panel,
}: {
  candidate: CardCandidate;
  testId: string;
  selectLabel: string;
  selected: boolean;
  onToggle: () => void;
  panel: ReactNode;
}) {
  const count = candidate.count_of_issues;
  const deck = candidate.description ? stripHtml(candidate.description) : '';
  return (
    <div className={styles.candidateCard} data-testid={testId}>
      <button
        type="button"
        className={styles.candidateBody}
        aria-label={selectLabel}
        aria-expanded={selected}
        disabled={candidate.have_it}
        onClick={onToggle}
      >
        <Poster
          initial={(candidate.name ?? '?').charAt(0)}
          src={candidate.image_url}
          alt={`${candidate.name ?? 'volume'} cover`}
          frameClassName={styles.posterFrame}
          fallbackClassName={styles.posterFallback}
          tint={publisherTint(candidate.publisher)}
          lazy
        />
        <span className={styles.candidateInfo}>
          <span className={styles.candidateTitleRow}>
            <span className={styles.candidateTitle}>
              {candidate.name ?? 'Unnamed volume'}
            </span>
            {candidate.start_year !== null && (
              <span className={styles.candidateYear}>({candidate.start_year})</span>
            )}
            {candidate.have_it && (
              <Chip tone="accent" className={styles.haveBadge} testId={`${testId}-have`}>
                <CheckIcon size={11} />
                In library
              </Chip>
            )}
            {candidate.ignored && (
              <Chip tone="muted" testId={`${testId}-ignored`}>
                Ignored
              </Chip>
            )}
          </span>
          <span className={styles.metaRow}>
            {candidate.publisher && (
              <span className={styles.metaItem}>{candidate.publisher}</span>
            )}
            {count !== null && (
              <span className={styles.metaItem}>
                {count} issue{count === 1 ? '' : 's'}
              </span>
            )}
            <span className={styles.metaItem}>via ComicVine</span>
          </span>
          {deck && <span className={styles.deck}>{deck}</span>}
        </span>
        <span className={styles.candidateTrailing} aria-hidden>
          {candidate.have_it && <CheckIcon size={20} />}
        </span>
      </button>
      {selected && !candidate.have_it && panel}
    </div>
  );
}

function AddOptionsPanel({
  candidate,
  busy,
  error,
  onAdd,
  onCancel,
}: {
  candidate: AddableCandidate;
  busy: boolean;
  error: string | null;
  onAdd: (options: AddOptions) => void;
  onCancel: () => void;
}) {
  const rootFolders = useRootFolders();
  const formatProfiles = useFormatProfiles();
  // null = not chosen yet -> default to the first entry once the list loads.
  const [rootFolderId, setRootFolderId] = useState<number | null>(null);
  const [formatProfileId, setFormatProfileId] = useState<number | null>(null);
  const [monitorStrategy, setMonitorStrategy] = useState('all');
  // '' = untouched -> the add carries NO booktype (derivation, FRG-SER-018).
  const [collectAs, setCollectAs] = useState<CollectAs>('');
  const [searchOnAdd, setSearchOnAdd] = useState(false);

  const selectedRootFolderId = rootFolderId ?? rootFolders.data?.[0]?.id ?? null;
  const selectedProfileId =
    formatProfileId ?? formatProfiles.data?.[0]?.id ?? null;
  // No-roots state (FRG-UI-012 first-run scenario): a fresh install has no
  // registered root folder, so adding is impossible — point at the settings
  // section where one can actually be created instead of a dead-end select.
  const noRootFolders =
    rootFolders.data !== undefined && rootFolders.data.length === 0;

  const monitorOptions: SegmentOption<string>[] = MONITOR_STRATEGIES.map((s) => ({
    value: s,
    label: STRATEGY_LABELS[s],
    testId: `monitor-${s}`,
  }));

  return (
    <div className={styles.addPanel} data-testid="add-options-panel">
      <div className={styles.selectGrid}>
        {noRootFolders ? (
          <p className={styles.errorNote} role="alert" data-testid="add-no-roots">
            No root folders are registered, so the series has nowhere to live.
            Add your comics folder as a root folder in{' '}
            <Link to="/settings/media-management">Media Management settings</Link>{' '}
            first.
          </p>
        ) : (
          <label className={styles.formField}>
            <span className={styles.fieldLabel}>Root Folder</span>
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
        <label className={styles.formField}>
          <span className={styles.fieldLabel}>Format Profile</span>
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
      </div>

      <div className={styles.formField}>
        <span className={styles.fieldLabel}>Monitor</span>
        <SegmentedControl
          options={monitorOptions}
          value={monitorStrategy}
          onChange={setMonitorStrategy}
          ariaLabel="Monitor strategy"
        />
      </div>

      <div className={styles.formField}>
        <span className={styles.fieldLabel}>Collect as</span>
        <SegmentedControl
          options={COLLECT_AS_OPTIONS}
          value={collectAs}
          onChange={setCollectAs}
          ariaLabel="Collect as"
        />
      </div>

      <label className={styles.checkboxRow}>
        <input
          type="checkbox"
          checked={searchOnAdd}
          onChange={(e) => setSearchOnAdd(e.target.checked)}
        />
        Start search for missing issues
      </label>

      {error && <p className={styles.errorNote}>{error}</p>}

      <div className={styles.panelActions}>
        <button
          type="button"
          className={styles.cancelButton}
          onClick={onCancel}
        >
          Cancel
        </button>
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
              // Untouched collect-as -> omit booktype (derivation); an explicit
              // choice sends the locked add-time book-type (FRG-SER-018).
              ...(collectAs ? { booktype: COLLECT_AS_BOOKTYPE[collectAs] } : {}),
            });
          }}
        >
          <PlusIcon size={13} />
          Add {candidate.name ?? 'series'}
        </button>
      </div>
    </div>
  );
}

export function AddSeries() {
  const navigate = useNavigate();
  const location = useLocation();
  const [input, setInput] = useState('');
  const [term, setTerm] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedSuggestionId, setSelectedSuggestionId] = useState<
    number | null
  >(null);
  // Per-search reveal of publisher-ignore-list volumes (FRG-UI-032); reset on
  // every new search so a fresh term always starts with them hidden.
  const [showIgnored, setShowIgnored] = useState(false);
  const lookup = useLookup(term, showIgnored);
  const suggest = useSuggest(input);
  const addSeries = useAddSeries();

  // Consume a prefilled term (FRG-UI-019 -> FRG-UI-005) via an effect rather
  // than a mount-time initializer: a SECOND navigation to the already-mounted
  // /add with a new term does not remount, so an initializer would silently
  // drop it. On each new prefill we seed the input and reset the search and
  // selection state so the debounced autosuggest fires for the new term, then
  // strip the consumed navigation state (replace) so browser Back/refresh does
  // not re-seed a stale prefill over the user's since-edited term.
  useEffect(() => {
    const prefill = (location.state as AddSeriesNavigationState | null)
      ?.prefillTerm;
    if (!prefill) return;
    setInput(prefill);
    setTerm('');
    setSelectedId(null);
    setSelectedSuggestionId(null);
    setShowIgnored(false);
    navigate(`${location.pathname}${location.search}`, {
      replace: true,
      state: null,
    });
  }, [location, navigate]);

  // A lookup error must never leak stale candidates from a previous outcome:
  // the results list and the outcome note both derive from this one value.
  const results = lookup.isError ? undefined : lookup.data;
  const note = lookupOutcomeNote(lookup.isError, lookup.error, results, term);
  // Publisher-ignore-list count (FRG-UI-032): how many candidates the server
  // hid. The recoverable "N hidden — Show" line renders only while they are
  // hidden and only when there is at least one; once revealed the line becomes
  // an "Edit list" pointer and the candidates show flagged.
  const hiddenByIgnore = results?.hidden_by_ignore_list ?? 0;

  // The autosuggest dropdown shows once the trimmed term clears the same
  // >=3-char threshold `useSuggest` gates on. It stays visible while ONE OF
  // ITS OWN candidates is selected (so that selection's inline add panel,
  // rendered inside this section below, remains on screen) but hides while a
  // FULL-LOOKUP candidate is selected instead, so the two add panels never
  // show at once.
  const suggestTerm = input.trim();
  // Once a full-lookup submission exists for EXACTLY the current input, the
  // authoritative results replace the passive suggest accelerator (design.md):
  // suppress the whole suggest surface so it cannot duplicate the lookup's
  // candidate list or its alert, nor leave a stale suggest error hanging under
  // a fresh same-term retry. It reappears the moment the input diverges from
  // the submitted term.
  const lookupSubmittedForInput = term.length > 0 && suggestTerm === term;
  // The dropdown lags the raw input by the debounce, so `suggest.data`/error
  // can still describe a superseded term for ~250ms after a keystroke. Render
  // the suggest surface only when the hook's settled (debounced) term matches
  // what is typed now — otherwise show nothing, never the old term's rows or a
  // still-open panel from a candidate that no longer belongs to the input.
  const suggestSettledForInput = suggest.settledTerm === suggestTerm;
  const showSuggest =
    suggestTerm.length >= 3 &&
    selectedId === null &&
    !lookupSubmittedForInput &&
    suggestSettledForInput;
  // Reuses the full lookup's outcome classifier verbatim (isComicVineAuthError
  // under the hood) so a suggest credential failure renders the SAME
  // actionable Settings-guidance text, structurally discriminated — never by
  // sniffing message prose, and never dressed up as an empty dropdown. Feeding
  // the suggest data (not undefined) also lets a degraded/part-way-failed
  // suggest surface as its failure note instead of a silent empty dropdown.
  // The accelerator keeps ONLY the hard-failure ('error') tone: 'status'
  // (incomplete/capped) falls through so the candidates it did return still
  // render, and 'plain' (clean empty) is left to the authoritative full lookup
  // rather than nagging under every partial term.
  const rawSuggestNote = showSuggest
    ? lookupOutcomeNote(suggest.isError, suggest.error, suggest.data, suggestTerm)
    : null;
  const suggestNote =
    rawSuggestNote?.tone === 'error' ? rawSuggestNote : null;
  const suggestCandidates =
    showSuggest && !suggest.isError ? suggest.data?.records ?? [] : [];

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSelectedId(null);
    setSelectedSuggestionId(null);
    setShowIgnored(false);
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

  const add = (candidate: AddableCandidate, options: AddOptions) => {
    const payload: SeriesCreatePayload = {
      cv_volume_id: candidate.cv_volume_id,
      root_folder_id: options.rootFolderId,
      format_profile_id: options.formatProfileId,
      monitor_strategy: options.monitorStrategy,
      monitor_new_items: 'all',
      search_on_add: options.searchOnAdd,
    };
    // Only carry the collect-as override when the operator chose one; an
    // untouched add omits the field so derivation stays byte-identical.
    if (options.booktype) payload.booktype = options.booktype;
    addSeries.mutate(payload, {
      onSuccess: (created) =>
        navigate(`/series/${created.id}`, {
          state: { refreshCommandId: created.refresh_command_id },
        }),
    });
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
                <OutcomeErrorText error={suggest.error} text={suggestNote.text} />
              </p>
            )}
            {!suggestNote &&
              suggestCandidates.map((candidate) => (
                <CandidateCard
                  key={candidate.cv_volume_id}
                  candidate={candidate}
                  testId={`suggest-${candidate.cv_volume_id}`}
                  selectLabel={`Select suggestion ${candidate.name ?? 'unnamed volume'}`}
                  selected={selectedSuggestionId === candidate.cv_volume_id}
                  onToggle={() =>
                    setSelectedSuggestionId(
                      selectedSuggestionId === candidate.cv_volume_id
                        ? null
                        : candidate.cv_volume_id,
                    )
                  }
                  panel={
                    <AddOptionsPanel
                      candidate={candidate}
                      busy={addSeries.isPending}
                      error={addSeries.error ? addSeries.error.message : null}
                      onAdd={(options) => add(candidate, options)}
                      onCancel={() => setSelectedSuggestionId(null)}
                    />
                  }
                />
              ))}
          </div>
        )}

        {lookup.isLoading && <p className={styles.stateNote}>Searching ComicVine…</p>}
        {note?.tone === 'error' && (
          <p className={styles.errorNote} role="alert">
            <OutcomeErrorText error={lookup.error} text={note.text} />
          </p>
        )}
        {note?.tone === 'status' && (
          <p className={styles.stateNote} role="status">
            {note.text}
          </p>
        )}
        {note?.tone === 'plain' && <p className={styles.stateNote}>{note.text}</p>}

        {hiddenByIgnore > 0 && !showIgnored && (
          <p
            className={styles.stateNote}
            role="status"
            data-testid="ignored-hidden-line"
          >
            {hiddenByIgnore} result{hiddenByIgnore === 1 ? '' : 's'} hidden by
            your publisher ignore list —{' '}
            <button
              type="button"
              className={styles.revealButton}
              onClick={() => setShowIgnored(true)}
            >
              Show
            </button>
          </p>
        )}
        {hiddenByIgnore > 0 && showIgnored && (
          <p
            className={styles.stateNote}
            role="status"
            data-testid="ignored-shown-line"
          >
            Showing results hidden by your publisher ignore list.{' '}
            <Link to="/settings/general">Edit list</Link>
          </p>
        )}

        <div className={styles.results}>
          {results?.records.map((candidate) => (
            <CandidateCard
              key={candidate.cv_volume_id}
              candidate={candidate}
              testId={`candidate-${candidate.cv_volume_id}`}
              selectLabel={`Select ${candidate.name ?? 'unnamed volume'}`}
              selected={selectedId === candidate.cv_volume_id}
              onToggle={() => {
                setSelectedSuggestionId(null);
                setSelectedId(
                  selectedId === candidate.cv_volume_id
                    ? null
                    : candidate.cv_volume_id,
                );
              }}
              panel={
                <AddOptionsPanel
                  candidate={candidate}
                  busy={addSeries.isPending}
                  error={addSeries.error ? addSeries.error.message : null}
                  onAdd={(options) => add(candidate, options)}
                  onCancel={() => setSelectedId(null)}
                />
              }
            />
          ))}
        </div>
      </div>
    </>
  );
}
