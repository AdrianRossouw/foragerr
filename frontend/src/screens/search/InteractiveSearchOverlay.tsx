import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Modal } from '../../components/Modal';
import { Popover } from '../../components/Popover';
import { useGrabRelease, useReleases } from '../../api/hooks';
import { ApiRequestError } from '../../api/fetcher';
import { queryKeys } from '../../api/queryKeys';
import type { ReleaseDecision } from '../../api/types';
import { formatAge, formatBytes } from '../../lib/format';
import styles from './InteractiveSearchOverlay.module.css';

export interface InteractiveSearchOverlayProps {
  issueId: number;
  /** Context for the title bar, e.g. "Saga #41". */
  contextTitle?: string;
  onClose: () => void;
}

interface GrabError {
  status: number | null;
  message: string;
}

const OUTCOME_LABEL: Record<ReleaseDecision['outcome'], string> = {
  approved: 'Approved',
  'temporarily-rejected': 'Temporarily rejected',
  rejected: 'Rejected',
};

const OUTCOME_CHIP: Record<ReleaseDecision['outcome'], string> = {
  approved: styles.chipApproved,
  'temporarily-rejected': styles.chipTemporary,
  rejected: styles.chipRejected,
};

/**
 * Interactive search overlay (FRG-UI-007) — the decision engine's
 * explainability surface. Every decision from GET /release renders as a row IN
 * THE ORDER THE ENDPOINT RETURNED IT (the comparator's order is the contract;
 * no client-side sorting), rejected rows expose their reasons VERBATIM, and
 * approved rows grab via the (indexer_id, guid) cache key. An expired cache
 * entry surfaces the backend's deterministic "search again" message distinctly.
 */
export function InteractiveSearchOverlay({
  issueId,
  contextTitle,
  onClose,
}: InteractiveSearchOverlayProps) {
  const { data, isLoading, isError, error } = useReleases(issueId);
  const grab = useGrabRelease();
  const queryClient = useQueryClient();
  const [grabError, setGrabError] = useState<GrabError | null>(null);
  const [grabbedKeys, setGrabbedKeys] = useState<ReadonlySet<string>>(new Set());
  const [pendingKey, setPendingKey] = useState<string | null>(null);

  const keyOf = (d: ReleaseDecision) => `${d.indexer_id}:${d.guid}`;
  const expired = grabError?.status === 404;

  const onGrab = (decision: ReleaseDecision) => {
    const key = keyOf(decision);
    setGrabError(null);
    setPendingKey(key);
    grab.mutate(
      { indexer_id: decision.indexer_id, guid: decision.guid },
      {
        onSuccess: () => setGrabbedKeys((prev) => new Set(prev).add(key)),
        onError: (err) =>
          setGrabError({
            status: err instanceof ApiRequestError ? err.status : null,
            message: err.message,
          }),
        onSettled: () => setPendingKey(null),
      },
    );
  };

  const searchAgain = () => {
    setGrabError(null);
    setGrabbedKeys(new Set());
    void queryClient.invalidateQueries({
      queryKey: queryKeys.release.forIssue(issueId),
    });
  };

  return (
    <Modal
      wide
      title={`Interactive Search${contextTitle ? ` — ${contextTitle}` : ''}`}
      label={`Interactive search${contextTitle ? ` for ${contextTitle}` : ''}`}
      onClose={onClose}
    >
      {grabError && (
        <div
          role="alert"
          className={expired ? styles.expiredBanner : styles.errorBanner}
          data-testid={expired ? 'grab-error-expired' : 'grab-error'}
        >
          {/* The backend's 404 message is deterministic — show it verbatim. */}
          <span>{expired ? grabError.message : `Grab failed: ${grabError.message}`}</span>
          {expired && (
            <button type="button" className={styles.bannerAction} onClick={searchAgain}>
              Search again
            </button>
          )}
        </div>
      )}

      {isLoading && <p className={styles.state}>Searching indexers…</p>}
      {isError && (
        <p role="alert" className={styles.state}>
          Search failed: {error.message}
        </p>
      )}
      {data && data.length === 0 && (
        <p className={styles.state}>No results from any enabled indexer.</p>
      )}

      {data && data.length > 0 && (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Decision</th>
              <th>Indexer</th>
              <th>Title</th>
              <th>Age</th>
              <th>Size</th>
              <th>Format</th>
              <th>Score</th>
              <th aria-label="Grab" />
            </tr>
          </thead>
          <tbody>
            {/* Row order = response order = comparator order. Never re-sort. */}
            {data.map((decision) => (
              <DecisionRow
                key={keyOf(decision)}
                decision={decision}
                grabbed={grabbedKeys.has(keyOf(decision))}
                pending={pendingKey === keyOf(decision)}
                onGrab={() => onGrab(decision)}
              />
            ))}
          </tbody>
        </table>
      )}
    </Modal>
  );
}

function DecisionRow({
  decision,
  grabbed,
  pending,
  onGrab,
}: {
  decision: ReleaseDecision;
  grabbed: boolean;
  pending: boolean;
  onGrab: () => void;
}) {
  const chipClass = `${styles.chip} ${OUTCOME_CHIP[decision.outcome]}`;
  const label = OUTCOME_LABEL[decision.outcome];

  return (
    <tr data-testid={`release-row-${decision.guid}`}>
      <td>
        {decision.rejections.length > 0 ? (
          <Popover
            trigger={<span className={chipClass}>! {label}</span>}
            label={`${label} — show reasons`}
          >
            {/* Verbatim reasons, one per line — never paraphrased (FRG-UI-007). */}
            <ul className={styles.rejectionList} data-testid={`ft-rejections-${decision.guid}`}>
              {decision.rejections.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </Popover>
        ) : (
          <span className={chipClass}>{label}</span>
        )}
      </td>
      <td className={styles.muted}>{decision.indexer_name}</td>
      <td className={styles.titleCell}>{decision.title}</td>
      <td className={styles.numeric}>{formatAge(decision.age_seconds)}</td>
      <td className={styles.numeric}>{formatBytes(decision.size_bytes)}</td>
      <td className={styles.muted}>{decision.format ?? '—'}</td>
      <td className={styles.numeric}>{decision.score}</td>
      <td>
        {decision.approved &&
          (grabbed ? (
            <span className={styles.grabbed}>Grabbed</span>
          ) : (
            <button
              type="button"
              className={styles.grabBtn}
              disabled={pending}
              aria-label={`Grab ${decision.title}`}
              onClick={onGrab}
            >
              {pending ? 'Grabbing…' : 'Grab'}
            </button>
          ))}
      </td>
    </tr>
  );
}
