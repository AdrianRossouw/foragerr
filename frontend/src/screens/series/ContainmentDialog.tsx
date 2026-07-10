import { useMemo, useState } from 'react';
import { Modal } from '../../components/Modal';
import { PlusIcon, TrashIcon } from '../../components/icons';
import {
  useDeleteContainment,
  useIssues,
  useSaveContainment,
  useSeriesIndex,
} from '../../api/hooks';
import type {
  CollectionRange,
  ContainmentRangeInput,
  SeriesResource,
} from '../../api/types';
import styles from './SeriesDetail.module.css';

/**
 * Containment declaration dialog (FRG-UI-026 / FRG-API-022). The operator
 * declares which single issues a collected edition's trade issue collects: one
 * target series PER sub-range (library only, never the trade itself) and a
 * start/end pair picked from that series' issue list. Save REPLACES all of the
 * trade issue's ranges (`PUT`); Delete all clears them (`DELETE`).
 *
 * Editing pre-fills each row from the read resource's RESOLVED endpoint issue
 * ids (FRG-API-022): a row whose stored endpoint no longer resolves to a live
 * issue renders a warning and must be re-picked before saving.
 */
export interface ContainmentDialogProps {
  /** The trade issue whose contents are being declared (the PUT/DELETE key). */
  anchorTradeIssueId: number;
  /** The trade series that owns that issue — excluded from the target picker. */
  anchorTradeSeriesId: number;
  /** Pre-selected target series (the collected single-issues run), if known. */
  defaultTargetSeriesId: number | null;
  /** The on-screen series whose collections view refreshes after a write. */
  invalidateSeriesId: number;
  /** Whether a declaration already exists (enables Delete all + edit copy). */
  hasExisting: boolean;
  /** The already-declared ranges (resolved endpoint ids) to pre-fill on edit. */
  existingRanges: CollectionRange[];
  onClose: () => void;
}

interface RangeRow {
  targetSeriesId: number | null;
  startIssueId: number | null;
  endIssueId: number | null;
  /** True when this row was pre-filled from a range whose stored endpoint no
   * longer resolves to a live issue — the operator must re-pick it. */
  needsRepick: boolean;
}

/** Build the initial rows: pre-fill from existing ranges, else one blank row. */
function initialRows(
  existingRanges: CollectionRange[],
  defaultTargetSeriesId: number | null,
): RangeRow[] {
  if (existingRanges.length > 0) {
    return existingRanges.map((r) => ({
      targetSeriesId: r.target_series_id,
      startIssueId: r.start_issue_id,
      endIssueId: r.end_issue_id,
      needsRepick: r.start_issue_id === null || r.end_issue_id === null,
    }));
  }
  return [
    {
      targetSeriesId: defaultTargetSeriesId,
      startIssueId: null,
      endIssueId: null,
      needsRepick: false,
    },
  ];
}

/**
 * One sub-range editor row: its OWN target series select plus the start/end
 * pickers backed by that series' issues. Kept a component so each row owns its
 * `useIssues` query (target series differ per row).
 */
function RangeRowEditor({
  index,
  row,
  targetOptions,
  canRemove,
  onChange,
  onRemove,
}: {
  index: number;
  row: RangeRow;
  targetOptions: SeriesResource[];
  canRemove: boolean;
  onChange: (patch: Partial<RangeRow>) => void;
  onRemove: () => void;
}) {
  // Dormant until this row has a target, so no `seriesId=0` request ever fires.
  const issuesQuery = useIssues(row.targetSeriesId ?? -1, row.targetSeriesId !== null);
  const issues = useMemo(() => issuesQuery.data ?? [], [issuesQuery.data]);
  const showWarning =
    row.needsRepick && (row.startIssueId === null || row.endIssueId === null);

  return (
    <div className={styles.rangeRow}>
      <label className={styles.rangeField}>
        <span>Series</span>
        <select
          aria-label={`Range ${index + 1} target series`}
          value={row.targetSeriesId ?? ''}
          onChange={(e) =>
            onChange({
              targetSeriesId: e.target.value === '' ? null : Number(e.target.value),
              // Endpoints belong to the target — reset them when it moves.
              startIssueId: null,
              endIssueId: null,
              needsRepick: false,
            })
          }
        >
          <option value="">Choose a series…</option>
          {targetOptions.map((s) => (
            <option key={s.id} value={s.id}>
              {s.title}
              {s.start_year !== null ? ` (${s.start_year})` : ''}
            </option>
          ))}
        </select>
      </label>
      <label className={styles.rangeField}>
        <span>From</span>
        <select
          aria-label={`Range ${index + 1} start issue`}
          disabled={row.targetSeriesId === null}
          value={row.startIssueId ?? ''}
          onChange={(e) =>
            onChange({
              startIssueId: e.target.value === '' ? null : Number(e.target.value),
            })
          }
        >
          <option value="">—</option>
          {issues.map((issue) => (
            <option key={issue.id} value={issue.id}>
              {issue.issue_number ?? `#${issue.id}`}
            </option>
          ))}
        </select>
      </label>
      <label className={styles.rangeField}>
        <span>To</span>
        <select
          aria-label={`Range ${index + 1} end issue`}
          disabled={row.targetSeriesId === null}
          value={row.endIssueId ?? ''}
          onChange={(e) =>
            onChange({
              endIssueId: e.target.value === '' ? null : Number(e.target.value),
            })
          }
        >
          <option value="">—</option>
          {issues.map((issue) => (
            <option key={issue.id} value={issue.id}>
              {issue.issue_number ?? `#${issue.id}`}
            </option>
          ))}
        </select>
      </label>
      {canRemove && (
        <button
          type="button"
          className={styles.iconDanger}
          aria-label={`Remove range ${index + 1}`}
          onClick={onRemove}
        >
          <TrashIcon size={14} />
        </button>
      )}
      {showWarning && (
        <p className={styles.errorNote} role="alert">
          This range&rsquo;s saved endpoint no longer exists — re-pick From/To.
        </p>
      )}
    </div>
  );
}

export function ContainmentDialog({
  anchorTradeIssueId,
  anchorTradeSeriesId,
  defaultTargetSeriesId,
  invalidateSeriesId,
  hasExisting,
  existingRanges,
  onClose,
}: ContainmentDialogProps) {
  const seriesIndex = useSeriesIndex();
  const [ranges, setRanges] = useState<RangeRow[]>(() =>
    initialRows(existingRanges, defaultTargetSeriesId),
  );

  const save = useSaveContainment(invalidateSeriesId);
  const remove = useDeleteContainment(invalidateSeriesId);

  const targetOptions = (seriesIndex.data ?? []).filter(
    (s) => s.id !== anchorTradeSeriesId,
  );

  const complete =
    ranges.length > 0 &&
    ranges.every(
      (r) =>
        r.targetSeriesId !== null &&
        r.startIssueId !== null &&
        r.endIssueId !== null,
    );

  const apiError = save.error?.message ?? remove.error?.message ?? null;

  const updateRange = (index: number, patch: Partial<RangeRow>) => {
    setRanges((rows) =>
      rows.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    );
  };

  // A new row defaults its target to the previous row's target so a multi-range
  // declaration over one series doesn't re-pick the series each time.
  const addRange = () =>
    setRanges((rows) => [
      ...rows,
      {
        targetSeriesId: rows[rows.length - 1]?.targetSeriesId ?? defaultTargetSeriesId,
        startIssueId: null,
        endIssueId: null,
        needsRepick: false,
      },
    ]);

  const removeRange = (index: number) =>
    setRanges((rows) => rows.filter((_, i) => i !== index));

  const onSave = () => {
    if (!complete) return;
    const payload: ContainmentRangeInput[] = ranges.map((r) => ({
      target_series_id: r.targetSeriesId as number,
      start_issue_id: r.startIssueId as number,
      end_issue_id: r.endIssueId as number,
    }));
    save.mutate({ issueId: anchorTradeIssueId, ranges: payload }, { onSuccess: onClose });
  };

  const busy = save.isPending || remove.isPending;
  const heading = hasExisting ? 'Edit contents' : 'Declare contents';

  return (
    <Modal
      title={heading}
      label={heading}
      onClose={onClose}
      footer={
        <div className={styles.dialogActions}>
          {hasExisting && (
            <button
              type="button"
              className={`${styles.button} ${styles.danger}`}
              disabled={busy}
              onClick={() => remove.mutate(anchorTradeIssueId, { onSuccess: onClose })}
            >
              Delete all
            </button>
          )}
          <span className={styles.actionsSpacer} />
          <button type="button" className={styles.button} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className={`${styles.button} ${styles.primary}`}
            disabled={!complete || busy}
            onClick={onSave}
          >
            Save
          </button>
        </div>
      }
    >
      <div className={styles.dialogForm}>
        <p className={styles.dialogHint}>
          Saving replaces all declared contents for this book.
        </p>

        <div className={styles.rangeList}>
          {ranges.map((row, index) => (
            <RangeRowEditor
              key={index}
              index={index}
              row={row}
              targetOptions={targetOptions}
              canRemove={ranges.length > 1}
              onChange={(patch) => updateRange(index, patch)}
              onRemove={() => removeRange(index)}
            />
          ))}
          <button type="button" className={styles.subtleButton} onClick={addRange}>
            <PlusIcon size={14} /> Add sub-range
          </button>
        </div>

        {apiError && (
          <p className={styles.errorNote} role="alert">
            {apiError}
          </p>
        )}
      </div>
    </Modal>
  );
}
