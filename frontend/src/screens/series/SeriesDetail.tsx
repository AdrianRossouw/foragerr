import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Toolbar } from '../../components/Toolbar';
import { MonitorToggle } from '../../components/MonitorToggle';
import { Menu } from '../../components/Menu';
import { Modal } from '../../components/Modal';
import { Poster } from '../../components/Poster';
import { BookTypeBadge } from '../../components/BookTypeBadge';
import { Chip, type ChipTone } from '../../components/Chip';
import { SegmentedControl } from '../../components/SegmentedControl';
import { ProgressStrip } from '../../components/ProgressStrip';
import {
  FolderScanIcon,
  MoreIcon,
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
  useCollections,
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
import { FORMAT_CHIP } from '../../theme/palettes';
import { useUiStore } from '../../store/uiStore';
import { InteractiveSearchOverlay } from '../search/InteractiveSearchOverlay';
import { fileFormat, formatBytes, formatDate } from '../../lib/format';
import type { BookType, IssueResource } from '../../api/types';
import { MONITOR_NEW_ITEMS_POLICIES } from '../../api/types';
import { CollectionsTab, type OpenContainment } from './CollectionsTab';
import { ContainmentDialog } from './ContainmentDialog';
import styles from './SeriesDetail.module.css';

/**
 * Series detail (FRG-UI-004), rebuilt to the M4 design: a hero over a blurred,
 * darkened LOCAL-cover backdrop, an icon-over-label action row dispatching the
 * existing commands, and a bordered panel carrying an Issues/Collections
 * segmented toggle. The Issues tab is a dense table with bulk selection
 * (FRG-UI-025); the Collections tab surfaces declared containment (FRG-UI-026).
 *
 * Issue numbers render VERBATIM as strings — "1.5"/"1.MU" are never coerced.
 * The e2e selector contract (`issue-row-<id>`, per-row search accessible names,
 * `interactive-search-overlay`, `command-status`) is unchanged.
 */

/** Book-type-toned collected-in chip colors, tokens-var neutral fallback. */
function collectedChipStyle(booktype: BookType) {
  const fc = FORMAT_CHIP[booktype];
  return fc
    ? { background: fc.bg, color: fc.text }
    : { background: 'var(--surface-menu)', color: 'var(--text-secondary)' };
}

/**
 * Issue status pill (FRG-UI-004): a file present reads success "Downloaded"; a
 * released issue with no file reads warn "Missing"; only a future-dated issue
 * reads neutral "Unreleased". Matches the backend's "released" semantics
 * (repo.wanted_issues): a dated issue is released once its date has passed, and
 * an issue with BOTH dates null is treated as released ("unknown-but-listed") —
 * so a fileless, dateless issue reads Missing, never Unreleased.
 */
function issueStatusPill(
  issue: IssueResource,
  nowMs: number,
): { label: string; tone: ChipTone } {
  if (issue.file) return { label: 'Downloaded', tone: 'success' };
  const iso = issue.store_date ?? issue.cover_date;
  const ms = iso ? Date.parse(iso) : NaN;
  // Both dates null → released (unknown-but-listed); a valid future date →
  // unreleased; a valid past date → released.
  const released = iso === null ? true : !Number.isNaN(ms) && ms <= nowMs;
  return released
    ? { label: 'Missing', tone: 'warning' }
    : { label: 'Unreleased', tone: 'neutral' };
}

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
    <Modal
      title={<strong>Delete — {title}</strong>}
      label={`Delete ${title}`}
      onClose={onCancel}
      footer={
        <>
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
        </>
      }
    >
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
        {error && (
          <p className={styles.errorNote} role="alert">
            {error}
          </p>
        )}
      </div>
    </Modal>
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
  const issueLabel = issue.issue_number ?? '—';

  const recycleConfigured = (mmQuery.data?.recycle_bin_path ?? '') !== '';
  const consequence = mmQuery.isLoading
    ? 'Checking the recycle-bin configuration…'
    : mmQuery.isError
      ? 'Could not read the recycle-bin configuration — the file may be permanently deleted.'
      : recycleConfigured
        ? 'This moves the file to the recycle bin.'
        : 'This permanently deletes the file from disk — no recycle bin is configured.';

  return (
    <Modal
      title={<strong>Delete File — #{issueLabel}</strong>}
      label={`Delete file for issue ${issueLabel}`}
      onClose={onClose}
      footer={
        <>
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
        </>
      }
    >
      <div className={styles.dialogBody}>
        {issue.file && <p className={styles.dialogPath}>{issue.file.path}</p>}
        <p>{consequence}</p>
        {/* Config fetch failed: the consequence is UNKNOWN, so Delete stays
            disabled (footer); offer an explicit retry rather than a dead end. */}
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
          <p className={styles.errorNote} role="alert">
            {deleteFile.error.message}
          </p>
        )}
      </div>
    </Modal>
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
    <Modal
      title={<strong>Edit — {title}</strong>}
      label={`Edit ${title}`}
      onClose={onCancel}
      footer={
        <>
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
        </>
      }
    >
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
    </Modal>
  );
}

/**
 * Overview paragraph with a measured show-more (FRG-UI-004, design decision 5).
 * Collapsed to a CSS line-clamp; the toggle renders ONLY when the text actually
 * overflows the clamp (scrollHeight vs clientHeight, re-measured on resize and
 * whenever the collapsed/expanded state flips so "show less" can re-collapse).
 */
function Overview({ text }: { text: string }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [overflowing, setOverflowing] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setOverflowing(el.scrollHeight > el.clientHeight + 1);
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [text, expanded]);

  return (
    <div className={styles.overviewWrap}>
      <p
        ref={ref}
        id="series-overview-text"
        className={expanded ? styles.overviewExpanded : styles.overview}
        data-testid="series-overview"
      >
        {text}
      </p>
      {(overflowing || expanded) && (
        <button
          type="button"
          className={styles.showMore}
          aria-expanded={expanded}
          aria-controls="series-overview-text"
          onClick={() => setExpanded((e) => !e)}
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
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
  const collectionsQuery = useCollections(seriesId);
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

  const [tab, setTab] = useState<'issues' | 'collections'>('issues');
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set());
  const [anchorId, setAnchorId] = useState<number | null>(null);
  const [showDelete, setShowDelete] = useState(false);
  const [showEdit, setShowEdit] = useState(false);
  const [showRename, setShowRename] = useState(false);
  const [overflowOpen, setOverflowOpen] = useState(false);
  const [deleteFileIssue, setDeleteFileIssue] = useState<IssueResource | null>(null);
  const [containment, setContainment] = useState<Parameters<OpenContainment>[0] | null>(
    null,
  );
  // Batch-scoped busy + partial-failure surface for "Search selected": true
  // while the per-issue commands dispatch; the whole bulk bar disables while it
  // runs (and while the last watched batch command is still live).
  const [batchSearching, setBatchSearching] = useState(false);
  const [batchNote, setBatchNote] = useState<string | null>(null);

  const interactiveIssueId = useUiStore((s) => s.interactiveSearchIssueId);
  const openInteractiveSearch = useUiStore((s) => s.openInteractiveSearch);
  const closeInteractiveSearch = useUiStore((s) => s.closeInteractiveSearch);
  // The overlay target is screen-scoped UI state; clear it when leaving.
  useEffect(() => closeInteractiveSearch, [closeInteractiveSearch]);

  const issues = useMemo(() => issuesQuery.data ?? [], [issuesQuery.data]);
  const collections = useMemo(
    () => collectionsQuery.data ?? [],
    [collectionsQuery.data],
  );
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

  const clearSelection = () => {
    setSelected(new Set());
    setAnchorId(null);
  };

  const toggleSelectAll = () => {
    setSelected(allSelected ? new Set() : new Set(issues.map((i) => i.id)));
    setAnchorId(null);
  };

  // Anchor-based selection (FRG-UI-025): a plain click toggles one row and
  // becomes the new anchor; a shift-click selects the visible-row span from the
  // anchor to the clicked row.
  const selectRow = (index: number, shiftKey: boolean) => {
    const id = issues[index].id;
    if (shiftKey && anchorId !== null) {
      const anchorIndex = issues.findIndex((i) => i.id === anchorId);
      if (anchorIndex !== -1) {
        const [lo, hi] =
          anchorIndex <= index ? [anchorIndex, index] : [index, anchorIndex];
        const next = new Set(selected);
        for (let k = lo; k <= hi; k += 1) next.add(issues[k].id);
        setSelected(next);
        return;
      }
    }
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
    setAnchorId(id);
  };

  const bulkSetMonitored = (monitored: boolean) => {
    if (selectedIssues.length === 0) return;
    bulkMonitor.mutate(
      { issueIds: selectedIssues.map((i) => i.id), monitored },
      { onSuccess: clearSelection },
    );
  };

  // Search selected: dispatch one automatic-search command per selected issue
  // SEQUENTIALLY through the command queue (await each — no parallel fan-out),
  // surfacing progress through the shared command-status surface. A re-entrancy
  // guard makes a second invocation inert while a batch is dispatching or its
  // last command is still live; partial failure surfaces as a role="alert"
  // note naming how many dispatched. The selection clears on full success.
  const bulkBusy = bulkMonitor.isPending || batchSearching || command.running;
  const searchSelected = async () => {
    if (bulkBusy) return;
    const targets = selectedIssues.map((i) => i.id);
    if (targets.length === 0) return;
    setBatchSearching(true);
    setBatchNote(null);
    let dispatched = 0;
    try {
      for (let idx = 0; idx < targets.length; idx += 1) {
        const record = await runCommand.mutateAsync({
          name: 'issue-search',
          payload: { series_id: seriesId, issue_id: targets[idx] },
        });
        dispatched += 1;
        setCommandLabel(`Search selected (${idx + 1}/${targets.length})`);
        start(record.id);
      }
      clearSelection();
    } catch {
      setBatchNote(
        `Search dispatched for ${dispatched} of ${targets.length} selected issue(s); the rest failed.`,
      );
    } finally {
      setBatchSearching(false);
    }
  };

  const openContainment: OpenContainment = (args) => setContainment(args);

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
  const backdrop = coverUrl(series);
  const nowMs = Date.now();

  const firstIssueIso = issues.length
    ? issues[0].store_date ?? issues[0].cover_date
    : null;
  const formats = Array.from(
    new Set(
      issues
        .map((i) => (i.file ? fileFormat(i.file.path) : null))
        .filter((f): f is string => f !== null && f !== ''),
    ),
  )
    .sort()
    .join(' / ');

  const commandChip = commandLabel && command.status && (
    <span className={styles.commandChip} data-testid="command-status">
      {commandLabel}: {command.status}
    </span>
  );

  return (
    <>
      <Toolbar title={series.title} />
      <div className={styles.content}>
        <section className={styles.hero}>
          {backdrop && (
            <div
              className={styles.heroBackdrop}
              style={{ backgroundImage: `url(${backdrop})` }}
              aria-hidden
            />
          )}
          <div className={styles.heroScrim} aria-hidden />
          <div className={styles.heroInner}>
            <Poster
              initial={series.title.charAt(0)}
              src={backdrop}
              alt={`${series.title} cover`}
              frameClassName={styles.posterFrame}
              fallbackClassName={styles.posterFallback}
            />
            <div className={styles.heroBody}>
              <div className={styles.titleRow}>
                <h1 className={styles.title}>{series.title}</h1>
                {series.start_year !== null && (
                  <span className={styles.year}>({series.start_year})</span>
                )}
                <BookTypeBadge booktype={series.booktype} />
              </div>

              <div className={styles.metaRow}>
                <span className={styles.metaMonitor}>
                  <MonitorToggle
                    monitored={series.monitored}
                    label="series"
                    size={14}
                    disabled={updateSeries.isPending}
                    onToggle={() => updateSeries.mutate({ monitored: !series.monitored })}
                  />
                  {series.monitored ? 'Monitored' : 'Unmonitored'}
                </span>
                {series.publisher && (
                  <>
                    <span className={styles.dot}>•</span>
                    <span>{series.publisher}</span>
                  </>
                )}
                {firstIssueIso && (
                  <>
                    <span className={styles.dot}>•</span>
                    <span>First issue {formatDate(firstIssueIso)}</span>
                  </>
                )}
                <span className={styles.dot}>•</span>
                <span>{series.status}</span>
                <span className={styles.dot}>•</span>
                <span>{stats.issue_count} issues</span>
                {formats && (
                  <>
                    <span className={styles.dot}>•</span>
                    <span>{formats}</span>
                  </>
                )}
              </div>

              <div className={styles.actionRow}>
                <button
                  type="button"
                  className={styles.action}
                  onClick={() => dispatch('Search', 'series-search', { series_id: seriesId })}
                >
                  <SearchIcon size={16} />
                  Search Monitored
                </button>
                <button
                  type="button"
                  className={styles.action}
                  onClick={() =>
                    dispatch('Search All', 'series-search', {
                      series_id: seriesId,
                      monitored_only: false,
                    })
                  }
                >
                  <SearchIcon size={16} />
                  Search All
                </button>
                <button
                  type="button"
                  className={styles.action}
                  onClick={() => dispatch('Refresh', 'refresh-series', { series_id: seriesId })}
                >
                  <RefreshIcon size={16} />
                  Refresh
                </button>
                <button
                  type="button"
                  className={styles.action}
                  onClick={() => setShowEdit(true)}
                >
                  <WrenchIcon size={15} />
                  Edit
                </button>
                <button
                  type="button"
                  className={`${styles.action} ${styles.actionDanger}`}
                  onClick={() => setShowDelete(true)}
                >
                  <TrashIcon size={15} />
                  Delete
                </button>
                <Menu
                  open={overflowOpen}
                  onOpenChange={setOverflowOpen}
                  label="More"
                  icon={<MoreIcon size={16} />}
                  align="end"
                  panelRole="menu"
                  testId="series-overflow-trigger"
                  menuTestId="series-overflow-menu"
                >
                  <button
                    type="button"
                    role="menuitem"
                    data-menuitem
                    className={styles.menuItem}
                    onClick={() => {
                      setOverflowOpen(false);
                      dispatch('Rescan', 'scan-series', { series_id: seriesId });
                    }}
                  >
                    <FolderScanIcon size={16} />
                    Rescan
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    data-menuitem
                    className={styles.menuItem}
                    onClick={() => {
                      setOverflowOpen(false);
                      setShowRename(true);
                    }}
                  >
                    <TableIcon size={16} />
                    Rename Files
                  </button>
                </Menu>
                {commandChip}
              </div>

              {series.description_sanitized && (
                <Overview text={series.description_sanitized} />
              )}
            </div>
          </div>
        </section>

        <div className={styles.panelWrap}>
          <div className={styles.panel}>
            <div className={styles.panelHeader}>
              <SegmentedControl
                ariaLabel="Detail view"
                value={tab}
                onChange={setTab}
                options={[
                  { value: 'issues', label: `Issues · ${stats.issue_count}` },
                  { value: 'collections', label: `Collections · ${collections.length}` },
                ]}
              />
              <span className={styles.panelSpacer} />
              <div className={styles.progressWrap}>
                <ProgressStrip
                  have={stats.file_count}
                  total={stats.issue_count}
                  monitored={series.monitored}
                  variant="strip"
                />
              </div>
            </div>

            {tab === 'issues' ? (
              <>
                {issuesQuery.isLoading && (
                  <p className={styles.stateNote}>Loading issues…</p>
                )}
                {issuesQuery.isError && (
                  <p className={styles.stateNote}>Could not load issues.</p>
                )}
                {selectedIssues.length > 0 && (
                  <div
                    className={styles.bulkBar}
                    role="region"
                    aria-label="Bulk issue actions"
                  >
                    <span className={styles.bulkCount} aria-live="polite">
                      {selectedIssues.length} selected
                    </span>
                    <button
                      type="button"
                      className={styles.button}
                      disabled={bulkBusy}
                      onClick={() => bulkSetMonitored(true)}
                    >
                      Monitor selected
                    </button>
                    <button
                      type="button"
                      className={styles.button}
                      disabled={bulkBusy}
                      onClick={() => bulkSetMonitored(false)}
                    >
                      Unmonitor selected
                    </button>
                    <button
                      type="button"
                      className={styles.button}
                      disabled={bulkBusy}
                      onClick={() => void searchSelected()}
                    >
                      Search selected
                    </button>
                    {batchNote && (
                      <span className={styles.errorNote} role="alert">
                        {batchNote}
                      </span>
                    )}
                  </div>
                )}
                {issues.length > 0 && (
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th scope="col" className={styles.selectCol}>
                          <input
                            type="checkbox"
                            aria-label="Select all issues"
                            checked={allSelected}
                            onChange={toggleSelectAll}
                          />
                        </th>
                        <th scope="col" className={styles.iconCol} />
                        <th scope="col" className={styles.numberCol}>Issue</th>
                        <th scope="col">Release</th>
                        <th scope="col">Status</th>
                        <th scope="col">Collected in</th>
                        <th scope="col" className={styles.sizeCol}>Size</th>
                        <th scope="col" className={styles.actionsCol} />
                      </tr>
                    </thead>
                    <tbody>
                      {issues.map((issue, index) => {
                        const status = issueStatusPill(issue, nowMs);
                        const memberships = issue.collected_in ?? [];
                        // Accessible names use the verbatim issue number (never
                        // the DB id) — a fileless/dateless issue with no number
                        // reads "issue —", not an internal row id.
                        const num = issue.issue_number ?? '—';
                        return (
                          <tr key={issue.id} data-testid={`issue-row-${issue.id}`}>
                            <td className={styles.selectCol}>
                              <input
                                type="checkbox"
                                aria-label={`Select issue ${num}`}
                                checked={selected.has(issue.id)}
                                onChange={() => {}}
                                onClick={(e) => selectRow(index, e.shiftKey)}
                              />
                            </td>
                            <td className={styles.iconCol}>
                              <MonitorToggle
                                monitored={issue.monitored}
                                label={`issue ${num}`}
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
                            {/* Verbatim string issue number — never coerced. */}
                            <td className={styles.numberCol}>
                              {issue.issue_number ?? '—'}
                            </td>
                            <td className={styles.mutedCell}>
                              {formatDate(issue.store_date ?? issue.cover_date)}
                            </td>
                            <td>
                              <Chip tone={status.tone}>{status.label}</Chip>
                            </td>
                            <td>
                              <div className={styles.collectedCell}>
                                {memberships.map((ci) => (
                                  <span
                                    key={ci.trade_issue_id}
                                    className={styles.collectedChip}
                                    style={collectedChipStyle(ci.booktype)}
                                    title={`${ci.trade_series_title} · ${ci.range_label}`}
                                  >
                                    {ci.range_label}
                                  </span>
                                ))}
                              </div>
                            </td>
                            <td className={styles.mutedCell}>
                              {issue.file ? formatBytes(issue.file.size) : '—'}
                            </td>
                            <td className={styles.actionsCol}>
                              <button
                                type="button"
                                className={styles.iconButton}
                                aria-label={`Automatic search for issue ${num}`}
                                title="Automatic search"
                                onClick={() =>
                                  dispatch(`Search #${num}`, 'issue-search', {
                                    series_id: seriesId,
                                    issue_id: issue.id,
                                  })
                                }
                              >
                                <SearchIcon size={14} />
                              </button>
                              <button
                                type="button"
                                className={styles.iconButton}
                                aria-label={`Interactive search for issue ${num}`}
                                title="Interactive search"
                                onClick={() => openInteractiveSearch(issue.id)}
                              >
                                <PersonIcon size={14} />
                              </button>
                              {issue.file && (
                                <button
                                  type="button"
                                  className={styles.iconDanger}
                                  aria-label={`Delete file for issue ${num}`}
                                  title="Delete file"
                                  onClick={() => setDeleteFileIssue(issue)}
                                >
                                  <TrashIcon size={14} />
                                </button>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </>
            ) : (
              <CollectionsTab
                series={series}
                seriesId={seriesId}
                collections={collections}
                ownIssues={issues}
                onOpenContainment={openContainment}
              />
            )}
          </div>
        </div>
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

      {containment && (
        <ContainmentDialog
          anchorTradeIssueId={containment.anchorTradeIssueId}
          anchorTradeSeriesId={containment.anchorTradeSeriesId}
          defaultTargetSeriesId={containment.defaultTargetSeriesId}
          invalidateSeriesId={seriesId}
          hasExisting={containment.hasExisting}
          existingRanges={containment.existingRanges}
          onClose={() => setContainment(null)}
        />
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

/**
 * Route wrapper (FRG-UI-004): keys {@link SeriesDetail} by the URL id so ALL
 * view-local state (active tab, bulk selection, expanded overview, command
 * status) fully resets when navigating series→series — e.g. a Collections
 * "Open" jump — instead of leaking the previous series' state into the next.
 */
export function SeriesDetailRoute() {
  const { id } = useParams();
  return <SeriesDetail key={id} />;
}
