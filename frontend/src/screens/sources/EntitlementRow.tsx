import { useState } from 'react';
import { Chip, type ChipTone } from '../../components/Chip';
import {
  useAddEntitlement,
  useEntitlementDetail,
  useIgnoreEntitlement,
  useMatchEntitlement,
  useRestoreEntitlement,
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
  const proposal = entitlement.proposed_match;

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
 * One reviewable entitlement row (FRG-UI-029): cover spine, title + format
 * chip, status tag, per-status actions (New → Match/Add/Ignore, Matched →
 * Change/Ignore, Ignored → Restore), a selection checkbox for bulk review, and
 * an expandable reconcile detail with issue chips.
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
  const [picking, setPicking] = useState(false);
  const match = useMatchEntitlement();
  const add = useAddEntitlement();
  const ignore = useIgnoreEntitlement();
  const restore = useRestoreEntitlement();
  const busy =
    match.isPending || add.isPending || ignore.isPending || restore.isPending;

  const status = entitlement.review_status;
  const proposal = entitlement.proposed_match;

  const doMatch = (seriesId: number) => {
    setPicking(false);
    match.mutate({ entitlementId: entitlement.id, seriesId });
  };

  const picker = (
    <select
      className={styles.picker}
      defaultValue=""
      aria-label="Match to a library series"
      data-testid={`match-picker-${entitlement.id}`}
      onChange={(e) => {
        const id = Number(e.target.value);
        if (id) doMatch(id);
      }}
    >
      <option value="" disabled>
        Match to…
      </option>
      {librarySeries.map((s) => (
        <option key={s.id} value={s.id}>
          {s.title}
        </option>
      ))}
    </select>
  );

  let actions;
  if (picking) {
    actions = (
      <>
        {picker}
        <button
          type="button"
          className={styles.mutedBtn}
          onClick={() => setPicking(false)}
        >
          Cancel
        </button>
      </>
    );
  } else if (status === 'ignored') {
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
          onClick={() => setPicking(true)}
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
            onClick={() => add.mutate(entitlement.id)}
            data-testid={`add-${entitlement.id}`}
          >
            Add {proposal.title ?? 'as new'}
          </button>
        ) : null}
        <button
          type="button"
          className={styles.mutedBtn}
          disabled={busy}
          onClick={() => setPicking(true)}
        >
          Match…
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
            {entitlement.preferred_format && (
              <Chip tone={formatTone(entitlement.preferred_format)}>
                {entitlement.preferred_format.toUpperCase()}
              </Chip>
            )}
          </div>
          <div className={styles.rowSub}>
            {[
              entitlement.publisher,
              entitlement.classification === 'other' ? 'Non-comic' : null,
            ]
              .filter(Boolean)
              .join(' · ') || 'Humble purchase'}
          </div>
          {entitlement.download_state === 'failed' && (
            <div className={styles.failedNote}>
              Download failed{entitlement.download_error ? `: ${entitlement.download_error}` : ''}
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
      {expanded && <ReconcileDetail entitlement={entitlement} />}
    </>
  );
}
