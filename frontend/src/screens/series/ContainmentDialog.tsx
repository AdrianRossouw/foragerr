import { useMemo, useState } from 'react';
import { Modal } from '../../components/Modal';
import { PlusIcon, TrashIcon } from '../../components/icons';
import {
  useDeleteContainment,
  useIssues,
  useSaveContainment,
  useSeriesIndex,
} from '../../api/hooks';
import type { ContainmentRangeInput } from '../../api/types';
import styles from './SeriesDetail.module.css';

/**
 * Containment declaration dialog (FRG-UI-026 / FRG-API-022). The operator
 * declares which single issues a collected edition's trade issue collects: one
 * target series (library only, never the trade itself) and one or more
 * start/end sub-ranges picked from that series' issue list. Save REPLACES all
 * of the trade issue's ranges (`PUT`); Delete all clears them (`DELETE`).
 *
 * The read resource (FRG-API-022) carries range LABELS, not endpoint issue ids,
 * so an edit pre-selects the target series but re-picks endpoints — matching
 * the replace-all write contract rather than pretending to round-trip labels.
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
  /** Whether a declaration already exists (enables Delete all). */
  hasExisting: boolean;
  onClose: () => void;
}

interface RangeRow {
  startIssueId: number | null;
  endIssueId: number | null;
}

export function ContainmentDialog({
  anchorTradeIssueId,
  anchorTradeSeriesId,
  defaultTargetSeriesId,
  invalidateSeriesId,
  hasExisting,
  onClose,
}: ContainmentDialogProps) {
  const seriesIndex = useSeriesIndex();
  const [targetSeriesId, setTargetSeriesId] = useState<number | null>(
    defaultTargetSeriesId,
  );
  const [ranges, setRanges] = useState<RangeRow[]>([
    { startIssueId: null, endIssueId: null },
  ]);

  const save = useSaveContainment(invalidateSeriesId);
  const remove = useDeleteContainment(invalidateSeriesId);

  // Issues of the chosen target series back the endpoint pickers; dormant until
  // a target is picked so no `seriesId=0` request ever fires.
  const targetIssuesQuery = useIssues(targetSeriesId ?? -1, targetSeriesId !== null);
  const targetIssues = useMemo(
    () => targetIssuesQuery.data ?? [],
    [targetIssuesQuery.data],
  );

  const targetOptions = (seriesIndex.data ?? []).filter(
    (s) => s.id !== anchorTradeSeriesId,
  );

  const complete =
    targetSeriesId !== null &&
    ranges.length > 0 &&
    ranges.every((r) => r.startIssueId !== null && r.endIssueId !== null);

  const apiError =
    save.error?.message ?? remove.error?.message ?? null;

  const onPickTarget = (value: string) => {
    setTargetSeriesId(value === '' ? null : Number(value));
    // Endpoints belong to the target series — reset them when the target moves.
    setRanges([{ startIssueId: null, endIssueId: null }]);
  };

  const updateRange = (index: number, patch: Partial<RangeRow>) => {
    setRanges((rows) =>
      rows.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    );
  };

  const addRange = () =>
    setRanges((rows) => [...rows, { startIssueId: null, endIssueId: null }]);

  const removeRange = (index: number) =>
    setRanges((rows) => rows.filter((_, i) => i !== index));

  const onSave = () => {
    if (!complete || targetSeriesId === null) return;
    const payload: ContainmentRangeInput[] = ranges.map((r) => ({
      target_series_id: targetSeriesId,
      start_issue_id: r.startIssueId as number,
      end_issue_id: r.endIssueId as number,
    }));
    save.mutate(
      { issueId: anchorTradeIssueId, ranges: payload },
      { onSuccess: onClose },
    );
  };

  const busy = save.isPending || remove.isPending;

  return (
    <Modal title="Declare contents" label="Declare contents" onClose={onClose}>
      <div className={styles.dialogForm}>
        <label className={styles.formRow}>
          <span>Collected series</span>
          <select
            aria-label="Target series"
            value={targetSeriesId ?? ''}
            onChange={(e) => onPickTarget(e.target.value)}
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

        <div className={styles.rangeList}>
          {ranges.map((row, index) => (
            <div className={styles.rangeRow} key={index}>
              <label className={styles.rangeField}>
                <span>From</span>
                <select
                  aria-label={`Range ${index + 1} start issue`}
                  disabled={targetSeriesId === null}
                  value={row.startIssueId ?? ''}
                  onChange={(e) =>
                    updateRange(index, {
                      startIssueId: e.target.value === '' ? null : Number(e.target.value),
                    })
                  }
                >
                  <option value="">—</option>
                  {targetIssues.map((issue) => (
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
                  disabled={targetSeriesId === null}
                  value={row.endIssueId ?? ''}
                  onChange={(e) =>
                    updateRange(index, {
                      endIssueId: e.target.value === '' ? null : Number(e.target.value),
                    })
                  }
                >
                  <option value="">—</option>
                  {targetIssues.map((issue) => (
                    <option key={issue.id} value={issue.id}>
                      {issue.issue_number ?? `#${issue.id}`}
                    </option>
                  ))}
                </select>
              </label>
              {ranges.length > 1 && (
                <button
                  type="button"
                  className={styles.iconDanger}
                  aria-label={`Remove range ${index + 1}`}
                  onClick={() => removeRange(index)}
                >
                  <TrashIcon size={14} />
                </button>
              )}
            </div>
          ))}
          <button
            type="button"
            className={styles.subtleButton}
            onClick={addRange}
            disabled={targetSeriesId === null}
          >
            <PlusIcon size={14} /> Add sub-range
          </button>
        </div>

        {apiError && <p className={styles.errorNote}>{apiError}</p>}
      </div>

      <div className={styles.dialogActions}>
        {hasExisting && (
          <button
            type="button"
            className={`${styles.button} ${styles.danger}`}
            disabled={busy}
            onClick={() =>
              remove.mutate(anchorTradeIssueId, { onSuccess: onClose })
            }
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
    </Modal>
  );
}
