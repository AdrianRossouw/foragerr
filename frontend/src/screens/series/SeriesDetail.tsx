import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Toolbar } from '../../components/Toolbar';
import { ToolbarButton, ToolbarSeparator } from '../../components/ToolbarButton';
import { MonitorToggle } from '../../components/MonitorToggle';
import { ProgressPill } from '../../components/ProgressPill';
import { Poster } from '../../components/Poster';
import { BookTypeBadge } from '../../components/BookTypeBadge';
import {
  BookmarkIcon,
  CloseIcon,
  FolderScanIcon,
  PersonIcon,
  RefreshIcon,
  SearchIcon,
  TableIcon,
  TrashIcon,
  WrenchIcon,
} from '../../components/icons';
import { RenamePreviewPanel } from '../settings/naming/RenamePreviewPanel';
import { useMediaManagementConfig } from '../settings/naming/namingHooks';
import {
  useBulkSetIssuesMonitored,
  useDeleteIssueFile,
  useDeleteSeries,
  useIssues,
  useRunCommand,
  useSeriesDetail,
  useSetIssueMonitored,
  useUpdateSeries,
  useWatchedCommand,
} from '../../api/hooks';
import { queryKeys } from '../../api/queryKeys';
import { coverUrl } from '../../api/urls';
import { useUiStore } from '../../store/uiStore';
import { InteractiveSearchOverlay } from '../search/InteractiveSearchOverlay';
import { fileFormat, formatBytes, formatDate } from '../../lib/format';
import type { IssueResource } from '../../api/types';
import { MONITOR_NEW_ITEMS_POLICIES } from '../../api/types';
import styles from './SeriesDetail.module.css';

/**
 * Series detail (FRG-UI-004): Sonarr-shaped hero band + command toolbar +
 * flat issue table (comics have no season layer). Issue numbers are rendered
 * VERBATIM as strings — "1.5" and "1.MU" must never be numerically coerced.
 * Series-level actions ride POST /api/v1/command; monitored toggles persist
 * via the series/issues PUT endpoints and write back into the query cache.
 */

function DeleteDialog({
  title,
  busy,
  error,
  commandStatus,
  onCancel,
  onConfirm,
}: {
  title: string;
  busy: boolean;
  error: string | null;
  /** Live status of the async delete-series-files command (202 path), if any. */
  commandStatus: string | null;
  onCancel: () => void;
  onConfirm: (deleteFiles: boolean) => void;
}) {
  const [deleteFiles, setDeleteFiles] = useState(false);
  return (
    <div className={styles.overlay}>
      <div role="dialog" aria-modal="true" aria-label={`Delete ${title}`} className={styles.dialog}>
        <header className={styles.dialogHeader}>
          <strong>Delete — {title}</strong>
          <button type="button" className={styles.iconButton} aria-label="Close" onClick={onCancel}>
            <CloseIcon size={14} />
          </button>
        </header>
        <div className={styles.dialogBody}>
          <p>The series will be removed from the library.</p>
          <label className={styles.checkboxRow}>
            <input
              type="checkbox"
              checked={deleteFiles}
              disabled={busy}
              onChange={(e) => setDeleteFiles(e.target.checked)}
            />
            Also delete files from disk
          </label>
          {/* Truthful since m2-daily-surfaces: deleteFiles=true is implemented
              (each file routed through the recycle bin before the rows go). */}
          <p className={styles.dialogHint}>
            Files are moved to the recycle bin when one is configured; otherwise
            they are permanently deleted. Unchecked, files stay on disk.
          </p>
          {/* deleteFiles=true returns 202: the file removal runs as a watched
              delete-series-files command whose status shows here until terminal. */}
          {commandStatus && (
            <p className={styles.dialogHint} data-testid="delete-command-status">
              Deleting files: {commandStatus}
            </p>
          )}
          {error && <p className={styles.errorNote}>{error}</p>}
        </div>
        <footer className={styles.dialogFooter}>
          <button type="button" className={styles.button} onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className={`${styles.button} ${styles.danger}`}
            disabled={busy}
            onClick={() => onConfirm(deleteFiles)}
          >
            Delete
          </button>
        </footer>
      </div>
    </div>
  );
}

/**
 * Per-issue delete-file confirmation (FRG-UI-004, m2-daily-surfaces). The
 * dialog names the real consequence by reading the media-management config
 * (mounted only while open, so the config is fetched on demand): a configured
 * recycle bin means the file is moved there; none means permanent deletion.
 * Confirm stays disabled until the consequence is known.
 */
function DeleteFileDialog({
  issue,
  seriesId,
  onClose,
}: {
  issue: IssueResource;
  seriesId: number;
  onClose: () => void;
}) {
  const mmQuery = useMediaManagementConfig();
  const deleteFile = useDeleteIssueFile(seriesId);
  const issueLabel = issue.issue_number ?? String(issue.id);

  const recycleConfigured = (mmQuery.data?.recycle_bin_path ?? '') !== '';
  const consequence = mmQuery.isLoading
    ? 'Checking the recycle-bin configuration…'
    : mmQuery.isError
      ? 'Could not read the recycle-bin configuration — the file may be permanently deleted.'
      : recycleConfigured
        ? 'This moves the file to the recycle bin.'
        : 'This permanently deletes the file from disk — no recycle bin is configured.';

  return (
    <div className={styles.overlay}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Delete file for issue ${issueLabel}`}
        className={styles.dialog}
      >
        <header className={styles.dialogHeader}>
          <strong>Delete File — #{issueLabel}</strong>
          <button
            type="button"
            className={styles.iconButton}
            aria-label="Close"
            onClick={onClose}
          >
            <CloseIcon size={14} />
          </button>
        </header>
        <div className={styles.dialogBody}>
          {issue.file && <p className={styles.dialogPath}>{issue.file.path}</p>}
          <p>{consequence}</p>
          {/* Config fetch failed: the consequence is UNKNOWN, so Delete stays
              disabled (below); offer an explicit retry rather than a dead end. */}
          {mmQuery.isError && (
            <button
              type="button"
              className={styles.button}
              disabled={mmQuery.isFetching}
              onClick={() => void mmQuery.refetch()}
            >
              {mmQuery.isFetching ? 'Retrying…' : 'Retry'}
            </button>
          )}
          {deleteFile.error && (
            <p className={styles.errorNote}>{deleteFile.error.message}</p>
          )}
        </div>
        <footer className={styles.dialogFooter}>
          <button type="button" className={styles.button} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className={`${styles.button} ${styles.danger}`}
            // Disabled until the consequence is KNOWN: no file, delete in
            // flight, config still loading, OR the config fetch errored.
            disabled={
              issue.file === null ||
              deleteFile.isPending ||
              mmQuery.isLoading ||
              mmQuery.isError
            }
            onClick={() => {
              if (issue.file) {
                deleteFile.mutate(issue.file.id, { onSuccess: onClose });
              }
            }}
          >
            Delete File
          </button>
        </footer>
      </div>
    </div>
  );
}

function EditDialog({
  title,
  monitorNewItems,
  busy,
  onCancel,
  onSave,
}: {
  title: string;
  monitorNewItems: string;
  busy: boolean;
  onCancel: () => void;
  onSave: (monitorNewItems: string) => void;
}) {
  const [policy, setPolicy] = useState(monitorNewItems);
  return (
    <div className={styles.overlay}>
      <div role="dialog" aria-modal="true" aria-label={`Edit ${title}`} className={styles.dialog}>
        <header className={styles.dialogHeader}>
          <strong>Edit — {title}</strong>
          <button type="button" className={styles.iconButton} aria-label="Close" onClick={onCancel}>
            <CloseIcon size={14} />
          </button>
        </header>
        <div className={styles.dialogBody}>
          <label className={styles.formRow}>
            <span>Monitor New Issues</span>
            <select value={policy} onChange={(e) => setPolicy(e.target.value)}>
              {MONITOR_NEW_ITEMS_POLICIES.map((p) => (
                <option key={p} value={p}>
                  {p === 'all' ? 'All new issues' : 'None'}
                </option>
              ))}
            </select>
          </label>
        </div>
        <footer className={styles.dialogFooter}>
          <button type="button" className={styles.button} onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className={`${styles.button} ${styles.primary}`}
            disabled={busy}
            onClick={() => onSave(policy)}
          >
            Save
          </button>
        </footer>
      </div>
    </div>
  );
}

function IssueStatusCell({ issue }: { issue: IssueResource }) {
  if (issue.file) {
    return (
      <span className={styles.fileChip}>
        {fileFormat(issue.file.path)} · {formatBytes(issue.file.size)}
      </span>
    );
  }
  return issue.monitored ? (
    <span className={styles.missingChip}>Missing</span>
  ) : (
    <span className={styles.mutedChip}>Unmonitored</span>
  );
}

export function SeriesDetail() {
  const { id } = useParams();
  const seriesId = Number(id);
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();

  const seriesQuery = useSeriesDetail(seriesId);
  const issuesQuery = useIssues(seriesId);
  const updateSeries = useUpdateSeries(seriesId);
  const deleteSeries = useDeleteSeries();
  const setIssueMonitored = useSetIssueMonitored(seriesId);
  const bulkMonitor = useBulkSetIssuesMonitored(seriesId);
  const runCommand = useRunCommand();

  // When a live command finishes, refresh the data it may have changed.
  const command = useWatchedCommand(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.series.detail(seriesId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.issues.forSeries(seriesId) });
  });
  const { start } = command;
  const [commandLabel, setCommandLabel] = useState<string | null>(null);

  // The deleteFiles path returns 202 + a delete-series-files command; watch it
  // so the dialog shows progress, then leave for the library once it finishes.
  // On completion the file_deleted history rows and Wanted changes have landed.
  const deleteCommand = useWatchedCommand((status) => {
    if (status === 'completed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.wanted.all() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.history.all() });
    }
    navigate('/');
  });

  // A refresh command queued by the add flow rides in as router state so the
  // detail screen shows it live on arrival (FRG-UI-005 add scenario).
  const refreshFromAdd = (location.state as { refreshCommandId?: number } | null)
    ?.refreshCommandId;
  useEffect(() => {
    if (refreshFromAdd !== undefined) {
      setCommandLabel('Refresh');
      start(refreshFromAdd);
    }
  }, [refreshFromAdd, start]);

  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set());
  const [showDelete, setShowDelete] = useState(false);
  const [showEdit, setShowEdit] = useState(false);
  const [showRename, setShowRename] = useState(false);
  const [deleteFileIssue, setDeleteFileIssue] = useState<IssueResource | null>(null);

  const interactiveIssueId = useUiStore((s) => s.interactiveSearchIssueId);
  const openInteractiveSearch = useUiStore((s) => s.openInteractiveSearch);
  const closeInteractiveSearch = useUiStore((s) => s.closeInteractiveSearch);
  // The overlay target is screen-scoped UI state; clear it when leaving.
  useEffect(() => closeInteractiveSearch, [closeInteractiveSearch]);

  const issues = useMemo(() => issuesQuery.data ?? [], [issuesQuery.data]);
  const allSelected = issues.length > 0 && issues.every((i) => selected.has(i.id));
  const selectedIssues = issues.filter((i) => selected.has(i.id));

  const dispatch = (label: string, name: string, payload: Record<string, unknown>) => {
    runCommand.mutate(
      { name, payload },
      {
        onSuccess: (record) => {
          setCommandLabel(label);
          start(record.id);
        },
      },
    );
  };

  const toggleSelectAll = () => {
    setSelected(allSelected ? new Set() : new Set(issues.map((i) => i.id)));
  };

  const toggleSelected = (issueId: number) => {
    const next = new Set(selected);
    if (next.has(issueId)) next.delete(issueId);
    else next.add(issueId);
    setSelected(next);
  };

  const bulkToggleMonitored = () => {
    if (selectedIssues.length === 0) return;
    const target = !selectedIssues.every((i) => i.monitored);
    bulkMonitor.mutate({ issueIds: selectedIssues.map((i) => i.id), monitored: target });
  };

  if (seriesQuery.isLoading) {
    return (
      <>
        <Toolbar title="Series" />
        <p className={styles.stateNote}>Loading series…</p>
      </>
    );
  }
  if (seriesQuery.isError || !seriesQuery.data) {
    return (
      <>
        <Toolbar title="Series" />
        <p className={styles.stateNote}>Could not load this series.</p>
      </>
    );
  }

  const series = seriesQuery.data;
  const stats = series.statistics;

  return (
    <>
      <Toolbar
        title={series.title}
        actions={
          <span className={styles.toolbarActions}>
            {commandLabel && command.status && (
              <span className={styles.commandChip} data-testid="command-status">
                {commandLabel}: {command.status}
              </span>
            )}
            <ToolbarButton
              icon={<RefreshIcon />}
              label="Refresh"
              onClick={() => dispatch('Refresh', 'refresh-series', { series_id: seriesId })}
            />
            <ToolbarButton
              icon={<FolderScanIcon />}
              label="Rescan"
              onClick={() => dispatch('Rescan', 'scan-series', { series_id: seriesId })}
            />
            <ToolbarButton
              icon={<SearchIcon />}
              label="Search Monitored"
              onClick={() => dispatch('Search', 'series-search', { series_id: seriesId })}
            />
            <ToolbarSeparator />
            <ToolbarButton
              icon={<TableIcon />}
              label="Rename Files"
              onClick={() => setShowRename(true)}
            />
            <ToolbarButton icon={<WrenchIcon />} label="Edit" onClick={() => setShowEdit(true)} />
            <ToolbarButton icon={<TrashIcon />} label="Delete" onClick={() => setShowDelete(true)} />
          </span>
        }
      />
      <div className={styles.content}>
        <section className={styles.hero}>
          <Poster
            initial={series.title.charAt(0)}
            src={coverUrl(series.id)}
            alt={`${series.title} cover`}
            frameClassName={styles.posterFrame}
            fallbackClassName={styles.posterFallback}
          />
          <div className={styles.heroBody}>
            <div className={styles.titleRow}>
              <MonitorToggle
                monitored={series.monitored}
                label="series"
                size={22}
                disabled={updateSeries.isPending}
                onToggle={() => updateSeries.mutate({ monitored: !series.monitored })}
              />
              <h1 className={styles.title}>{series.title}</h1>
              {series.start_year !== null && (
                <span className={styles.year}>({series.start_year})</span>
              )}
            </div>
            <div className={styles.chipRow}>
              <BookTypeBadge booktype={series.booktype} />
              <span className={styles.chip}>{series.path}</span>
              <span className={styles.chip}>{formatBytes(stats.size_on_disk)}</span>
              {series.publisher && <span className={styles.chip}>{series.publisher}</span>}
              <span className={styles.chip}>{series.status}</span>
              <span className={styles.chip}>
                {series.monitored ? 'Monitored' : 'Unmonitored'}
              </span>
            </div>
            {series.description_sanitized && (
              <p className={styles.overview}>{series.description_sanitized}</p>
            )}
            <div className={styles.statsRow}>
              <ProgressPill
                have={stats.file_count}
                total={stats.issue_count}
                monitored={series.monitored}
              />
              <span>
                {stats.issue_count} issues · {stats.file_count} files ·{' '}
                {stats.missing_count} missing
              </span>
            </div>
          </div>
        </section>

        {issuesQuery.isLoading && <p className={styles.stateNote}>Loading issues…</p>}
        {issuesQuery.isError && <p className={styles.stateNote}>Could not load issues.</p>}
        {issues.length > 0 && (
          <table className={styles.table}>
            <thead>
              <tr>
                <th className={styles.selectCol}>
                  <input
                    type="checkbox"
                    aria-label="Select all issues"
                    checked={allSelected}
                    onChange={toggleSelectAll}
                  />
                </th>
                <th className={styles.iconCol}>
                  <button
                    type="button"
                    className={styles.bulkMonitorButton}
                    aria-label="Toggle monitored for selected issues"
                    title="Toggle monitored for selected issues"
                    disabled={selectedIssues.length === 0 || bulkMonitor.isPending}
                    onClick={bulkToggleMonitored}
                  >
                    <BookmarkIcon filled size={14} />
                  </button>
                </th>
                <th className={styles.numberCol}>#</th>
                <th>Title</th>
                <th>Cover Date</th>
                <th>Status</th>
                <th className={styles.actionsCol}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {issues.map((issue) => (
                <tr key={issue.id} data-testid={`issue-row-${issue.id}`}>
                  <td className={styles.selectCol}>
                    <input
                      type="checkbox"
                      aria-label={`Select issue ${issue.issue_number ?? issue.id}`}
                      checked={selected.has(issue.id)}
                      onChange={() => toggleSelected(issue.id)}
                    />
                  </td>
                  <td className={styles.iconCol}>
                    <MonitorToggle
                      monitored={issue.monitored}
                      label={`issue ${issue.issue_number ?? issue.id}`}
                      size={14}
                      disabled={setIssueMonitored.isPending}
                      onToggle={() =>
                        setIssueMonitored.mutate({
                          issueId: issue.id,
                          monitored: !issue.monitored,
                        })
                      }
                    />
                  </td>
                  {/* Verbatim string issue number — never coerced (FRG-UI-004). */}
                  <td className={styles.numberCol}>{issue.issue_number ?? '—'}</td>
                  <td>{issue.title ?? '—'}</td>
                  <td>{formatDate(issue.cover_date)}</td>
                  <td>
                    <IssueStatusCell issue={issue} />
                  </td>
                  <td className={styles.actionsCol}>
                    <button
                      type="button"
                      className={styles.iconButton}
                      aria-label={`Automatic search for issue ${issue.issue_number ?? issue.id}`}
                      title="Automatic search"
                      onClick={() =>
                        dispatch(
                          `Search #${issue.issue_number ?? issue.id}`,
                          'issue-search',
                          { series_id: seriesId, issue_id: issue.id },
                        )
                      }
                    >
                      <SearchIcon size={14} />
                    </button>
                    <button
                      type="button"
                      className={styles.iconButton}
                      aria-label={`Interactive search for issue ${issue.issue_number ?? issue.id}`}
                      title="Interactive search"
                      onClick={() => openInteractiveSearch(issue.id)}
                    >
                      <PersonIcon size={14} />
                    </button>
                    {issue.file && (
                      <button
                        type="button"
                        className={styles.iconDanger}
                        aria-label={`Delete file for issue ${issue.issue_number ?? issue.id}`}
                        title="Delete file"
                        onClick={() => setDeleteFileIssue(issue)}
                      >
                        <TrashIcon size={14} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/*
       * Interactive-search mount seam (FRG-UI-007): the real overlay mounts
       * here; the launch contract (uiStore.interactiveSearchIssueId) is the
       * stable part. The wrapper carries the overlay's scoping attributes.
       */}
      {interactiveIssueId !== null && (
        <div
          data-testid="interactive-search-overlay"
          data-issue-id={interactiveIssueId}
        >
          <InteractiveSearchOverlay
            issueId={interactiveIssueId}
            contextTitle={series.title}
            onClose={closeInteractiveSearch}
          />
        </div>
      )}

      {showDelete && (
        <DeleteDialog
          title={series.title}
          busy={deleteSeries.isPending || deleteCommand.running}
          error={deleteSeries.error ? deleteSeries.error.message : null}
          commandStatus={deleteCommand.status}
          onCancel={() => setShowDelete(false)}
          onConfirm={(deleteFiles) =>
            deleteSeries.mutate(
              { seriesId, deleteFiles },
              {
                onSuccess: (result) => {
                  // 202 → watch the delete-series-files command (navigate when it
                  // finishes); 204 plain delete → the series is already gone.
                  if (result) deleteCommand.start(result.id);
                  else navigate('/');
                },
              },
            )
          }
        />
      )}

      {deleteFileIssue && (
        <DeleteFileDialog
          issue={deleteFileIssue}
          seriesId={seriesId}
          onClose={() => setDeleteFileIssue(null)}
        />
      )}

      {showRename && (
        <RenamePreviewPanel
          seriesId={seriesId}
          seriesTitle={series.title}
          onClose={() => setShowRename(false)}
        />
      )}

      {showEdit && (
        <EditDialog
          title={series.title}
          monitorNewItems={series.monitor_new_items}
          busy={updateSeries.isPending}
          onCancel={() => setShowEdit(false)}
          onSave={(monitorNewItems) =>
            updateSeries.mutate(
              { monitor_new_items: monitorNewItems },
              { onSuccess: () => setShowEdit(false) },
            )
          }
        />
      )}
    </>
  );
}
