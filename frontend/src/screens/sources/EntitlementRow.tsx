import { useState } from 'react';
import { BookTypeBadge } from '../../components/BookTypeBadge';
import { Chip, type ChipTone } from '../../components/Chip';
import {
  EntitlementSearch,
  searchSeedTerm,
  type PickedCandidate,
} from './EntitlementSearch';
import { proposalState } from './proposal';
import {
  useAddEntitlement,
  useEntitlementDetail,
  useIgnoreEntitlement,
  useMatchEntitlement,
  useRestoreEntitlement,
  useRetryDownload,
} from '../../api/sourceHooks';
import type {
  EntitlementResource,
  FillSet,
  SeriesResource,
} from '../../api/types';
import styles from './sources.module.css';

/** Above this issue count a range renders text-only (design handoff edge rule). */
const CHIP_SUPPRESS_ABOVE = 12;

function formatTone(format: string | null): ChipTone {
  if (!format) return 'muted';
  const f = format.toUpperCase();
  if (f === 'CBZ' || f === 'CBR' || f === 'CB7' || f === 'CBT') return 'info';
  if (f === 'PDF') return 'warning';
  return 'muted';
}

function pct(confidence: number): string {
  return `${Math.round(confidence * 100)}%`;
}

/** The reconcile explanation + issue chips for one expanded entitlement. */
function ReconcileDetail({ entitlement }: { entitlement: EntitlementResource }) {
  const { data, isLoading } = useEntitlementDetail(entitlement.id, true);
  const state = proposalState(entitlement);
  const proposal = state.kind === 'candidate' ? state.candidate : null;

  let explain: string;
  if (entitlement.review_status === 'matched') {
    explain =
      'Linked to your library — this collected edition fills the issues below.';
  } else if (entitlement.review_status === 'ignored') {
    explain = 'Ignored — excluded from review. Restore to bring it back.';
  } else if (proposal?.kind === 'library') {
    explain = `Proposed match: ${proposal.title ?? 'a library series'} (in your library, ${pct(proposal.confidence)} confidence). Match to link this edition to it.`;
  } else if (proposal?.kind === 'comicvine') {
    explain = `Proposed match: ${proposal.title ?? 'a new series'} (add from ComicVine, ${pct(proposal.confidence)} confidence). Add to create it and file this edition.`;
  } else if (state.kind === 'not-computed') {
    explain =
      'Match not computed yet — it runs on the next sync. Pick a series to match, or ignore.';
  } else {
    explain = 'No confident match yet — pick a series to match, or ignore.';
  }

  return (
    <div className={styles.detail} data-testid={`detail-${entitlement.id}`}>
      <div className={styles.detailExplain}>{explain}</div>
      {isLoading && <div>Loading reconcile detail…</div>}
      {data?.fill_sets.map((fs) => (
        <FillSetView key={fs.trade_issue_id} fillSet={fs} />
      ))}
    </div>
  );
}

function FillSetView({ fillSet }: { fillSet: FillSet }) {
  if (fillSet.standalone) {
    return (
      <div className={styles.rangeBlock}>
        No single issues to fill — kept as a standalone edition / one-shot.
      </div>
    );
  }
  const ownedSingles = fillSet.ranges
    .flatMap((r) => r.issues)
    .filter((i) => i.ownership === 'single');

  return (
    <>
      {fillSet.ranges.map((range) => {
        const suppressed = range.issues.length > CHIP_SUPPRESS_ABOVE;
        return (
          <div className={styles.rangeBlock} key={range.range_label}>
            <div className={styles.rangeLabel}>
              Collects #{range.range_label}
            </div>
            {suppressed ? (
              <div>
                Marks {range.issues.length} issues (#{range.range_label}) as
                owned.
              </div>
            ) : (
              <div className={styles.chips}>
                {range.issues.map((issue) => {
                  const owned = issue.ownership === 'single';
                  return (
                    <span
                      key={issue.issue_id}
                      className={`${styles.issueChip} ${owned ? styles.chipOwned : styles.chipFill}`}
                      title={
                        owned
                          ? 'Already owned as a separate single issue'
                          : 'Will be filled by this edition'
                      }
                      data-owned={owned ? 'true' : 'false'}
                    >
                      #{issue.issue_number ?? '?'}
                    </span>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
      {ownedSingles.length > 0 && (
        <div className={styles.reconcileNote}>
          <i className="fa-solid fa-code-branch" aria-hidden />
          <span>
            You already own{' '}
            {ownedSingles.map((i) => `#${i.issue_number ?? '?'}`).join(', ')} as
            a separate single issue. Foragerr keeps the single and fills only the
            remaining issues — no double-counting.
          </span>
        </div>
      )}
    </>
  );
}

/**
 * One reviewable entitlement row (FRG-UI-029): cover spine, title + a chip
 * (a matched row's linked library series booktype when it has one, else the
 * source file's format), status tag, per-status actions (New → accept the
 * proposal / Search ComicVine / Ignore, Matched → Change (the same search) /
 * Ignore, Ignored → Restore), a selection checkbox for bulk review, an
 * expandable ComicVine search panel (FRG-UI-039 — present on every reviewable
 * row, so a row with no proposal is still resolvable), and an expandable
 * reconcile detail with issue chips.
 */
export function EntitlementRow({
  entitlement,
  index,
  selected,
  onSelectRow,
  expanded,
  onToggleExpand,
  librarySeries,
}: {
  entitlement: EntitlementResource;
  index: number;
  selected: boolean;
  onSelectRow: (index: number, shiftKey: boolean) => void;
  expanded: boolean;
  onToggleExpand: () => void;
  librarySeries: SeriesResource[];
}) {
  const [searching, setSearching] = useState(false);
  const match = useMatchEntitlement();
  const add = useAddEntitlement();
  const ignore = useIgnoreEntitlement();
  const restore = useRestoreEntitlement();
  const retry = useRetryDownload();
  const busy =
    match.isPending ||
    add.isPending ||
    ignore.isPending ||
    restore.isPending ||
    retry.isPending;

  const status = entitlement.review_status;
  // Three wire shapes, three different sentences (FRG-SRC-010): a candidate, a
  // stored "we looked and nothing fit" verdict, and a not-yet-computed row. Only
  // the first is an acceptable proposal; none of them is a dead end.
  const state = proposalState(entitlement);
  const proposal = state.kind === 'candidate' ? state.candidate : null;

  // Matched rows link to a real library series, whose collected-edition
  // booktype (FRG-SER-018) is the truer chip than the source file's format —
  // it is what the mock shows (design handoff: sources-connected.png). `new`
  // rows have no linked series yet, so they always fall back to the format
  // chip; a matched row whose series has no booktype (a single-issues run)
  // also falls back to the format chip.
  const matchedSeries =
    status === 'matched' && entitlement.matched_series_id != null
      ? librarySeries.find((s) => s.id === entitlement.matched_series_id)
      : undefined;
  const matchedBooktype = matchedSeries?.booktype ?? null;

  const doMatch = (seriesId: number) => {
    setSearching(false);
    match.mutate({ entitlementId: entitlement.id, seriesId });
  };

  /**
   * A picked ComicVine candidate resolves one of two ways (FRG-UI-039 / the
   * FRG-SRC-008 seam): a volume already in the library links straight to that
   * series (nothing is created), and one that is not adds it and matches in a
   * single action. `have_it` is ComicVine-side truth; the library series id it
   * maps to is resolved locally by cv_volume_id against the full series index.
   * If the overlay cannot name the local series (it went stale — the volume
   * was added since the index was fetched), the add path still carries the
   * explicit cv_volume_id and the backend degrades it to a match
   * (FRG-SRC-008) — so a pick is never a dead end either.
   */
  const pickCandidate = (candidate: PickedCandidate) => {
    setSearching(false);
    if (candidate.have_it) {
      const owned = librarySeries.find(
        (s) => s.cv_volume_id === candidate.cv_volume_id,
      );
      if (owned) {
        match.mutate({ entitlementId: entitlement.id, seriesId: owned.id });
        return;
      }
    }
    add.mutate({
      entitlementId: entitlement.id,
      cvVolumeId: candidate.cv_volume_id,
    });
  };

  // The automatic verdict, rendered BESIDE the search rather than as a wall:
  // "no plausible match" describes what the proposal pass concluded, never
  // what the operator can still do (FRG-UI-039).
  const searchNote =
    status === 'matched'
      ? 'Change this match — search ComicVine for the right volume.'
      : proposal
        ? `Automatic proposal: ${proposal.title ?? 'a candidate'} (${pct(proposal.confidence)}). Search ComicVine if it is wrong.`
        : state.kind === 'not-computed'
          ? 'Match not computed yet — search ComicVine for the right volume.'
          : 'No plausible automatic match — search ComicVine for the right volume.';

  let actions;
  if (status === 'ignored') {
    actions = (
      <button
        type="button"
        className={styles.linkBtn}
        disabled={busy}
        onClick={() => restore.mutate(entitlement.id)}
        data-testid={`restore-${entitlement.id}`}
      >
        Restore
      </button>
    );
  } else if (status === 'matched') {
    actions = (
      <>
        <button
          type="button"
          className={styles.linkBtn}
          disabled={busy}
          aria-expanded={searching}
          onClick={() => setSearching(!searching)}
          data-testid={`search-${entitlement.id}`}
        >
          Change…
        </button>
        <button
          type="button"
          className={styles.mutedBtn}
          disabled={busy}
          onClick={() => ignore.mutate(entitlement.id)}
        >
          Ignore
        </button>
      </>
    );
  } else {
    // new
    actions = (
      <>
        {proposal?.kind === 'library' && entitlement.proposed_series_id != null ? (
          <button
            type="button"
            className={styles.linkBtn}
            disabled={busy}
            onClick={() => doMatch(entitlement.proposed_series_id as number)}
            data-testid={`match-${entitlement.id}`}
          >
            Match to {proposal.title ?? 'suggestion'}
          </button>
        ) : proposal?.kind === 'comicvine' ? (
          <button
            type="button"
            className={styles.linkBtn}
            disabled={busy}
            onClick={() => add.mutate({ entitlementId: entitlement.id })}
            data-testid={`add-${entitlement.id}`}
          >
            Add {proposal.title ?? 'as new'}
          </button>
        ) : (
          // No proposal is not a dead end — the verdict sits beside the search
          // affordance, which is always there (FRG-UI-039). "Nothing fit" and
          // "not looked at yet" are different facts, so they read differently.
          <span
            className={styles.noMatchNote}
            data-testid={`no-match-${entitlement.id}`}
            data-verdict={state.kind}
          >
            {state.kind === 'not-computed'
              ? 'Match not computed yet'
              : 'No plausible match'}
          </span>
        )}
        <button
          type="button"
          className={styles.mutedBtn}
          disabled={busy}
          aria-expanded={searching}
          onClick={() => setSearching(!searching)}
          data-testid={`search-${entitlement.id}`}
        >
          Search ComicVine…
        </button>
        <button
          type="button"
          className={styles.mutedBtn}
          disabled={busy}
          onClick={() => ignore.mutate(entitlement.id)}
          data-testid={`ignore-${entitlement.id}`}
        >
          Ignore
        </button>
      </>
    );
  }

  const tag =
    status === 'matched' ? (
      <span className={`${styles.statusTag} ${styles.tagMatched}`}>
        <i className="fa-solid fa-link" aria-hidden /> Matched
      </span>
    ) : status === 'ignored' ? (
      <span className={`${styles.statusTag} ${styles.tagIgnored}`}>
        <i className="fa-solid fa-eye-slash" aria-hidden /> Ignored
      </span>
    ) : (
      <span className={`${styles.statusTag} ${styles.tagNew}`}>
        <i className="fa-solid fa-sparkles" aria-hidden /> New
      </span>
    );

  return (
    <>
      <div
        className={`${styles.row} ${status === 'ignored' ? styles.rowIgnored : ''}`}
        data-testid={`entitlement-row-${entitlement.id}`}
        data-status={status}
      >
        <input
          type="checkbox"
          className={styles.checkbox}
          checked={selected}
          aria-label={`Select ${entitlement.human_name}`}
          onChange={() => {}}
          onClick={(e) => onSelectRow(index, e.shiftKey)}
          data-testid={`select-${entitlement.id}`}
        />
        <span className={styles.spine} aria-hidden>
          {(entitlement.preferred_format ?? '').slice(0, 3).toUpperCase()}
        </span>
        <div className={styles.rowMain}>
          <div className={styles.rowTitle}>
            <span className={styles.rowName}>{entitlement.human_name}</span>
            {matchedBooktype ? (
              <BookTypeBadge booktype={matchedBooktype} />
            ) : (
              entitlement.preferred_format && (
                <Chip tone={formatTone(entitlement.preferred_format)}>
                  {entitlement.preferred_format.toUpperCase()}
                </Chip>
              )
            )}
          </div>
          <div className={styles.rowSub}>
            {[
              entitlement.publisher,
              entitlement.classification === 'other' ? 'Non-comic' : null,
            ]
              .filter(Boolean)
              .join(' · ') || 'Humble purchase'}
            {/* Bundle provenance (FRG-SRC-011), subtle: it is what "select
                bundle" names, so the operator can see which bundle a row came
                from without opening anything. */}
            {entitlement.bundle_human_name && (
              <span
                className={styles.bundleName}
                data-testid={`bundle-${entitlement.id}`}
              >
                {' · '}
                {entitlement.bundle_human_name}
              </span>
            )}
          </div>
          {entitlement.download_state === 'failed' && (
            <div className={styles.failedNote}>
              Download failed{entitlement.download_error ? `: ${entitlement.download_error}` : ''}
              {/* The failure is terminal until the operator acts (FRG-SRC-009):
                  Retry clears it and re-queues the grab. */}
              <button
                type="button"
                className={styles.retryBtn}
                disabled={busy}
                onClick={() => retry.mutate(entitlement.id)}
                data-testid={`retry-${entitlement.id}`}
              >
                {retry.isPending ? 'Retrying…' : 'Retry'}
              </button>
            </div>
          )}
        </div>
        {tag}
        <div className={styles.rowActions}>{actions}</div>
        <button
          type="button"
          className={styles.caret}
          aria-label={expanded ? 'Collapse detail' : 'Expand detail'}
          aria-expanded={expanded}
          onClick={onToggleExpand}
          data-testid={`expand-${entitlement.id}`}
        >
          <i className={`fa-solid ${expanded ? 'fa-chevron-up' : 'fa-chevron-down'}`} />
        </button>
      </div>
      {searching && (
        <EntitlementSearch
          entitlementId={entitlement.id}
          seedTerm={searchSeedTerm(entitlement.human_name)}
          busy={busy}
          noteText={searchNote}
          onPick={pickCandidate}
          onCancel={() => setSearching(false)}
        />
      )}
      {expanded && <ReconcileDetail entitlement={entitlement} />}
    </>
  );
}
