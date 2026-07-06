import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Toolbar } from '../../components/Toolbar';
import { Poster } from '../../components/Poster';
import { SearchIcon, CloseIcon } from '../../components/icons';
import {
  useAddSeries,
  useFormatProfiles,
  useLookup,
  useRootFolders,
} from '../../api/hooks';
import type { LookupCandidate } from '../../api/types';
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
 * Does a lookup error message name the ComicVine API key as the cause? The
 * backend maps a ComicVine auth failure to a 503 whose message names both
 * ComicVine and its API key (FRG-API-003); other 503s (upstream down) do not.
 * Kept deliberately narrow to that credential wording so the actionable
 * "check Settings" guidance only fires for a missing/invalid key.
 */
export function isComicVineAuthMessage(message: string | null | undefined): boolean {
  if (!message) return false;
  const m = message.toLowerCase();
  return m.includes('comicvine') && m.includes('api key');
}

const STRATEGY_LABELS: Record<string, string> = {
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
  candidate: LookupCandidate;
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

  return (
    <div className={styles.addPanel} data-testid="add-options-panel">
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
  const [input, setInput] = useState('');
  const [term, setTerm] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const lookup = useLookup(term);
  const addSeries = useAddSeries();

  // A missing/invalid ComicVine key is an actionable credential error, not the
  // plain "no results" state (FRG-UI-005); every other lookup failure stays a
  // generic retry message.
  const isCredentialError =
    lookup.isError && isComicVineAuthMessage(lookup.error?.message);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSelectedId(null);
    setTerm(normalizeLookupTerm(input));
  };

  const add = (
    candidate: LookupCandidate,
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

        {lookup.isLoading && <p className={styles.stateNote}>Searching ComicVine…</p>}
        {isCredentialError && (
          <p className={styles.errorNote} role="alert">
            ComicVine API key missing or invalid — check Settings.
          </p>
        )}
        {lookup.isError && !isCredentialError && (
          <p className={styles.errorNote} role="alert">
            ComicVine lookup failed. Try again in a moment.
          </p>
        )}
        {lookup.data && !lookup.data.complete && (
          <p className={styles.stateNote} role="status">
            Results may be incomplete — ComicVine did not return everything.
          </p>
        )}
        {lookup.data && lookup.data.complete && lookup.data.records.length === 0 && (
          <p className={styles.stateNote}>No volumes found for “{term}”.</p>
        )}

        <div className={styles.results}>
          {lookup.data?.records.map((candidate) => (
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
                onClick={() =>
                  setSelectedId(
                    selectedId === candidate.cv_volume_id
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
