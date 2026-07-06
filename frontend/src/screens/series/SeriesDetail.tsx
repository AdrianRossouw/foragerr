import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Toolbar } from '../../components/Toolbar';
import { ToolbarButton, ToolbarSeparator } from '../../components/ToolbarButton';
import { MonitorToggle } from '../../components/MonitorToggle';
import { ProgressPill } from '../../components/ProgressPill';
import { Poster } from '../../components/Poster';
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
import {
  useBulkSetIssuesMonitored,
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
  onCancel,
  onConfirm,
}: {
  title: string;
  busy: boolean;
  error: string | null;
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
              onChange={(e) => setDeleteFiles(e.target.checked)}
            />
            Also delete files from disk
          </label>
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
          busy={deleteSeries.isPending}
          error={deleteSeries.error ? deleteSeries.error.message : null}
          onCancel={() => setShowDelete(false)}
          onConfirm={(deleteFiles) =>
            deleteSeries.mutate(
              { seriesId, deleteFiles },
              { onSuccess: () => navigate('/') },
            )
          }
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
