import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Modal } from '../../components/Modal';
import { ReasonsPopover } from '../../components/ReasonsPopover';
import {
  useIssues,
  useSeriesIndex,
  useWatchedCommand,
} from '../../api/hooks';
import { queryKeys } from '../../api/queryKeys';
import { ARCHIVE_FORMATS } from '../../api/types';
import type { ManualImportEntry, ManualImportFileSpec } from '../../api/types';
import { formatBytes } from '../../lib/format';
import {
  manualImportKey,
  useExecuteManualImport,
  useManualImportCandidates,
  type ManualImportSource,
} from './manualImportHooks';
import styles from './ManualImportOverlay.module.css';

/** Per-row operator override state, seeded from the API's suggested mapping. */
interface RowOverride {
  seriesId: number | null;
  issueId: number | null;
  format: string | null;
}

export interface ManualImportOverlayProps {
  /** The single candidate source — a managed path OR a blocked download. */
  source: ManualImportSource;
  /** Context for the title bar, e.g. the download title or folder name. */
  contextTitle?: string;
  onClose: () => void;
}

/**
 * Manual-import overlay (FRG-UI-014) — the import pipeline's manual-override
 * surface, modeled on `InteractiveSearchOverlay`. Every candidate from GET
 * /manual-import renders as a row IN THE ORDER THE ENDPOINT RETURNED IT (no
 * client-side sorting); a blocked row exposes its rejection reasons VERBATIM via
 * a popover. Each row's series/issue/format controls are pre-filled from the
 * API's suggested mapping (a verified embedded ComicInfo suggestion is badged),
 * and the footer posts the corrected mappings as a single `manual-import`
 * command. On the command completing, the candidate list refetches — imported
 * files leave, still-blocked files re-render with their updated reasons — and
 * the queue view is invalidated.
 */
export function ManualImportOverlay({
  source,
  contextTitle,
  onClose,
}: ManualImportOverlayProps) {
  const { data, isLoading, isError, error } = useManualImportCandidates(source);
  const seriesIndex = useSeriesIndex();
  const execute = useExecuteManualImport();
  const queryClient = useQueryClient();

  const [overrides, setOverrides] = useState<Map<string, RowOverride>>(new Map());
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());

  // The confirm button follows the LIVE command status through the shared
  // watcher (same machinery as RenamePreviewPanel/LibraryImport): it re-enables
  // once the command reaches a terminal status, preventing a duplicate POST
  // while one is running. On completion the candidate list refetches (imported
  // files leave; still-blocked files re-render with updated reasons) and the
  // queue view is invalidated — whatever the terminal status, the refetched
  // rows are the honest per-file truth.
  const command = useWatchedCommand(() => {
    void queryClient.invalidateQueries({ queryKey: manualImportKey(source) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.queue.all() });
  });
  const { status, running: inProgress } = command;
  const finished = status !== null && !inProgress ? status : null;

  // Seed override + selection state from the candidate list. Runs on first load
  // AND on the post-import refetch (new array reference): imported files drop
  // out, still-blocked files re-seed with their updated reasons, and approved
  // rows are preselected. Because the query never refetches behind the user's
  // back (staleTime Infinity), in-flight edits are never clobbered mid-session.
  useEffect(() => {
    if (!data) return;
    const nextOverrides = new Map<string, RowOverride>();
    const nextSelected = new Set<string>();
    for (const entry of data) {
      nextOverrides.set(entry.path, {
        seriesId: entry.suggestedSeriesId,
        issueId: entry.suggestedIssueId,
        format: entry.format,
      });
      if (entry.approved) nextSelected.add(entry.path);
    }
    setOverrides(nextOverrides);
    setSelected(nextSelected);
  }, [data]);

  const seedFor = (entry: ManualImportEntry): RowOverride => ({
    seriesId: entry.suggestedSeriesId,
    issueId: entry.suggestedIssueId,
    format: entry.format,
  });

  const overrideFor = (entry: ManualImportEntry): RowOverride =>
    overrides.get(entry.path) ?? seedFor(entry);

  const updateOverride = (entry: ManualImportEntry, patch: Partial<RowOverride>) =>
    setOverrides((prev) => {
      const next = new Map(prev);
      next.set(entry.path, { ...(prev.get(entry.path) ?? seedFor(entry)), ...patch });
      return next;
    });

  const toggleSelected = (path: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  // A row is importable when it is already approved, or an override supplies
  // both a series and an issue (a blocked row becomes "plausibly importable").
  const isSelectable = (entry: ManualImportEntry, ov: RowOverride) =>
    entry.approved || (ov.seriesId !== null && ov.issueId !== null);

  const candidates = data ?? [];
  const picked = candidates.filter((entry) => {
    const ov = overrideFor(entry);
    return selected.has(entry.path) && isSelectable(entry, ov);
  });

  const onConfirm = () => {
    const files: ManualImportFileSpec[] = picked.map((entry) => {
      const ov = overrideFor(entry);
      return {
        path: entry.path,
        seriesId: ov.seriesId,
        issueId: ov.issueId,
        format: ov.format,
      };
    });
    // When the overlay was opened for a blocked download, carry that
    // downloadId so the backend re-evaluates with download scope (e.g.
    // AlreadyImportedSpec); a path-picker overlay omits it.
    execute.mutate(
      {
        files,
        downloadId: source.kind === 'download' ? source.downloadId : undefined,
      },
      { onSuccess: (cmd) => command.start(cmd.id) },
    );
  };

  const seriesOptions = seriesIndex.data ?? [];
  const submitting = inProgress || execute.isPending;

  return (
    <Modal
      wide
      title={`Manual Import${contextTitle ? ` — ${contextTitle}` : ''}`}
      label={`Manual import${contextTitle ? ` for ${contextTitle}` : ''}`}
      onClose={onClose}
      footer={
        <>
          {status && (
            <span className={styles.commandChip} data-testid="manual-command-status">
              Import: {status}
            </span>
          )}
          <span className={styles.footerSpacer} />
          <button type="button" className={styles.btn} onClick={onClose}>
            {finished ? 'Close' : 'Cancel'}
          </button>
          <button
            type="button"
            className={`${styles.btn} ${styles.btnPrimary}`}
            disabled={picked.length === 0 || submitting}
            onClick={onConfirm}
            data-testid="manual-import-confirm"
          >
            {submitting ? 'Importing…' : `Import ${picked.length} selected`}
          </button>
        </>
      }
    >
      {execute.isError && (
        <div role="alert" className={styles.errorBanner} data-testid="manual-import-error">
          Import failed: {execute.error.message}
        </div>
      )}

      {isLoading && <p className={styles.state}>Inspecting candidates…</p>}
      {isError && (
        <p role="alert" className={styles.state}>
          Could not list candidates: {error.message}
        </p>
      )}
      {data && data.length === 0 && (
        <p className={styles.state}>No candidate files found here.</p>
      )}

      {data && data.length > 0 && (
        <table className={styles.table}>
          <thead>
            <tr>
              <th aria-label="Select" />
              <th>Decision</th>
              <th>File</th>
              <th>Size</th>
              <th>Series</th>
              <th>Issue</th>
              <th>Format</th>
            </tr>
          </thead>
          <tbody>
            {/* Row order = response order = pipeline order. Never re-sort. */}
            {candidates.map((entry) => {
              const ov = overrideFor(entry);
              const selectable = isSelectable(entry, ov);
              return (
                <CandidateRow
                  key={entry.path}
                  entry={entry}
                  override={ov}
                  selectable={selectable}
                  checked={selected.has(entry.path) && selectable}
                  seriesOptions={seriesOptions.map((s) => ({ id: s.id, title: s.title }))}
                  onToggle={() => toggleSelected(entry.path)}
                  onSeriesChange={(seriesId) =>
                    // Changing series invalidates the previously chosen issue.
                    updateOverride(entry, { seriesId, issueId: null })
                  }
                  onIssueChange={(issueId) => updateOverride(entry, { issueId })}
                  onFormatChange={(format) => updateOverride(entry, { format })}
                />
              );
            })}
          </tbody>
        </table>
      )}
    </Modal>
  );
}

function CandidateRow({
  entry,
  override,
  selectable,
  checked,
  seriesOptions,
  onToggle,
  onSeriesChange,
  onIssueChange,
  onFormatChange,
}: {
  entry: ManualImportEntry;
  override: RowOverride;
  selectable: boolean;
  checked: boolean;
  seriesOptions: { id: number; title: string }[];
  onToggle: () => void;
  onSeriesChange: (seriesId: number | null) => void;
  onIssueChange: (issueId: number | null) => void;
  onFormatChange: (format: string | null) => void;
}) {
  return (
    <tr data-testid={`manual-row-${entry.name}`}>
      <td>
        <input
          type="checkbox"
          checked={checked}
          disabled={!selectable}
          aria-label={`Select ${entry.name}`}
          onChange={onToggle}
        />
      </td>
      <td>
        {entry.approved ? (
          <span className={`${styles.chip} ${styles.chipApproved}`}>Approved</span>
        ) : (
          <ReasonsPopover
            reasons={entry.rejections}
            label={`${entry.name} — show reasons`}
            chipClassName={`${styles.chip} ${styles.chipBlocked}`}
            chipContent={<>! Blocked</>}
            listTestId={`ft-manual-rejections-${entry.name}`}
          />
        )}
      </td>
      <td className={styles.fileCell}>
        {entry.name}
        {entry.folder && <span className={styles.folder}>{entry.folder}</span>}
      </td>
      <td className={styles.numeric}>{formatBytes(entry.size)}</td>
      <td>
        <select
          className={styles.select}
          aria-label={`Series for ${entry.name}`}
          value={override.seriesId ?? ''}
          onChange={(e) =>
            onSeriesChange(e.target.value === '' ? null : Number(e.target.value))
          }
        >
          <option value="">— Select series —</option>
          {seriesOptions.map((s) => (
            <option key={s.id} value={s.id}>
              {s.title}
            </option>
          ))}
        </select>
      </td>
      <td>
        <IssueSelect
          seriesId={override.seriesId}
          value={override.issueId}
          fileName={entry.name}
          onChange={onIssueChange}
        />
        {entry.embedded.verified && (
          <span className={styles.embeddedBadge} data-testid={`manual-embedded-${entry.name}`}>
            from ComicInfo
          </span>
        )}
      </td>
      <td>
        <select
          className={styles.select}
          aria-label={`Format for ${entry.name}`}
          value={override.format ?? ''}
          onChange={(e) => onFormatChange(e.target.value === '' ? null : e.target.value)}
        >
          <option value="">— Auto —</option>
          {ARCHIVE_FORMATS.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
          {/* Preserve a suggested format outside the known vocabulary. */}
          {override.format &&
            !ARCHIVE_FORMATS.includes(
              override.format as (typeof ARCHIVE_FORMATS)[number],
            ) && <option value={override.format}>{override.format}</option>}
        </select>
      </td>
    </tr>
  );
}

/**
 * The issue picker for one row, scoped to the row's chosen series (FRG-UI-014).
 * When no series is chosen it renders a disabled placeholder WITHOUT mounting an
 * issues query — only once a series is picked does it fetch that series' issues.
 */
function IssueSelect(props: {
  seriesId: number | null;
  value: number | null;
  fileName: string;
  onChange: (issueId: number | null) => void;
}) {
  if (props.seriesId === null) {
    return (
      <select
        className={styles.select}
        aria-label={`Issue for ${props.fileName}`}
        value=""
        disabled
        onChange={() => {}}
      >
        <option value="">— Select issue —</option>
      </select>
    );
  }
  return <LoadedIssueSelect {...props} seriesId={props.seriesId} />;
}

function LoadedIssueSelect({
  seriesId,
  value,
  fileName,
  onChange,
}: {
  seriesId: number;
  value: number | null;
  fileName: string;
  onChange: (issueId: number | null) => void;
}) {
  const issues = useIssues(seriesId);
  return (
    <select
      className={styles.select}
      aria-label={`Issue for ${fileName}`}
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
    >
      <option value="">— Select issue —</option>
      {(issues.data ?? []).map((issue) => (
        <option key={issue.id} value={issue.id}>
          {issue.issue_number ?? '?'}
          {issue.title ? ` — ${issue.title}` : ''}
        </option>
      ))}
    </select>
  );
}
