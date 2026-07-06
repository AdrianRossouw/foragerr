import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Toolbar } from '../../components/Toolbar';
import { Poster } from '../../components/Poster';
import { ReasonsPopover } from '../../components/ReasonsPopover';
import {
  useCommandStatus,
  useFormatProfiles,
  useLookup,
  useRootFolders,
} from '../../api/hooks';
import { queryKeys } from '../../api/queryKeys';
import { MONITOR_STRATEGIES } from '../../api/types';
import type { LibraryImportGroup } from '../../api/types';
import {
  lookupOutcomeNote,
  normalizeLookupTerm,
  STRATEGY_LABELS,
} from '../add/AddSeries';
import {
  libraryImportKey,
  useExecuteLibraryImport,
  useLibraryImportGroups,
  usePatchLibraryImportGroup,
  useStartLibraryScan,
  type LibraryImportGroupPatch,
} from './libraryImportHooks';
import styles from './LibraryImport.module.css';

/** Command lifecycle statuses that mean a watched command is still running. */
const LIVE_STATUSES = new Set(['queued', 'started']);

/**
 * Library import (FRG-UI-015): scan a configured root folder for unmapped
 * series folders (as a watched `library-import-scan` command), review the
 * staged groups — proposed ComicVine match with parse confidence, or an
 * explicit no-match state — correct matches via the inline ComicVine lookup,
 * then bulk-add the selected groups with batch add options through the shared
 * import pipeline, rendering per-group imported/blocked outcomes (blocked
 * reasons verbatim, à la the manual-import overlay).
 */

/**
 * Watch one dispatched command à la ManualImportOverlay: `start(id)` after the
 * POST, a live status chip while it runs, and `onFinished` exactly once when
 * it reaches a terminal status (then the watcher resets).
 */
function useWatchedCommand(onFinished: (status: string) => void): {
  status: string | null;
  running: boolean;
  start: (commandId: number) => void;
} {
  const [commandId, setCommandId] = useState<number | null>(null);
  const commandQuery = useCommandStatus(commandId);
  const status = commandQuery.data?.status ?? (commandId !== null ? 'queued' : null);
  const running = status !== null && LIVE_STATUSES.has(status);
  const finished = status !== null && !running ? status : null;

  // Ref'd callback: the effect must fire once per terminal transition, not on
  // every render where the caller's inline closure gets a new identity.
  const onFinishedRef = useRef(onFinished);
  onFinishedRef.current = onFinished;
  useEffect(() => {
    if (!finished) return;
    setCommandId(null);
    onFinishedRef.current(finished);
  }, [finished]);

  return { status, running, start: setCommandId };
}

/**
 * A group may be selected for import only when it carries a ComicVine match:
 * user-confirmed, or proposed WITH an attached volume. A no-match group (or a
 * proposed group whose lazy proposal never arrived) requires the explicit
 * inline-lookup choice first — mass import never guesses (FRG-IMP-023).
 */
function isSelectable(group: LibraryImportGroup): boolean {
  return (
    group.state === 'confirmed' ||
    (group.state === 'proposed' && group.proposedCvVolumeId !== null)
  );
}

export function LibraryImport() {
  const queryClient = useQueryClient();
  const rootFolders = useRootFolders();
  const [pickedRootId, setPickedRootId] = useState<number | null>(null);
  // Default to the first configured root once the list loads (add-flow style).
  const rootId = pickedRootId ?? rootFolders.data?.[0]?.id ?? null;
  const root = rootFolders.data?.find((folder) => folder.id === rootId) ?? null;

  const groupsQuery = useLibraryImportGroups(rootId);
  const scan = useStartLibraryScan();
  const patchGroup = usePatchLibraryImportGroup(rootId);
  const execute = useExecuteLibraryImport();

  // Roots whose scan completed THIS session: distinguishes "scan found nothing
  // (fully mapped)" from "nothing staged yet — run a scan" when the list is empty.
  const [scannedRoots, setScannedRoots] = useState<ReadonlySet<number>>(new Set());
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set());

  // The root a running scan was started for — invalidate THAT root's staging
  // on completion even if the picker moved meanwhile.
  const scanRootRef = useRef<number | null>(null);
  const scanCommand = useWatchedCommand(() => {
    const scannedId = scanRootRef.current;
    if (scannedId === null) return;
    setScannedRoots((prev) => new Set(prev).add(scannedId));
    void queryClient.invalidateQueries({ queryKey: libraryImportKey(scannedId) });
  });

  const executeCommand = useWatchedCommand(() => {
    // Per-group outcomes live in the staging rows; imported groups created
    // series, so the library index is stale too.
    if (rootId !== null) {
      void queryClient.invalidateQueries({ queryKey: libraryImportKey(rootId) });
    }
    void queryClient.invalidateQueries({
      queryKey: queryKeys.series.all(),
      exact: true,
    });
  });

  // Seed the selection from the staged list: importable groups preselect (the
  // manual-import overlay's convention). Runs on first load and on each
  // post-command/PATCH refetch — imported/skipped groups drop out, corrected
  // groups become selected. staleTime Infinity means no refetch ever clobbers
  // the set behind the user's back.
  useEffect(() => {
    if (!groupsQuery.data) return;
    const next = new Set<number>();
    for (const group of groupsQuery.data) {
      if (isSelectable(group)) next.add(group.id);
    }
    setSelected(next);
  }, [groupsQuery.data]);

  const toggleSelected = (groupId: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return next;
    });

  const startScan = () => {
    if (rootId === null) return;
    scanRootRef.current = rootId;
    scan.mutate(
      { rootFolderId: rootId },
      { onSuccess: (cmd) => scanCommand.start(cmd.id) },
    );
  };

  const groups = groupsQuery.data ?? [];
  const picked = groups.filter(
    (group) => selected.has(group.id) && isSelectable(group),
  );
  const busy =
    patchGroup.isPending || execute.isPending || executeCommand.running;

  const unconfigured = rootFolders.data !== undefined && rootFolders.data.length === 0;

  return (
    <>
      <Toolbar title="Library Import" />
      <div className={styles.content}>
        {rootFolders.isLoading && (
          <p className={styles.stateNote}>Loading root folders…</p>
        )}
        {rootFolders.isError && (
          <p role="alert" className={styles.errorNote}>
            Could not load root folders: {rootFolders.error.message}
          </p>
        )}

        {/* Unconfigured state (FRG-UI-015): explicit, pointing at Settings. */}
        {unconfigured && (
          <p className={styles.stateNote} data-testid="li-unconfigured">
            No root folders are configured, so there is nothing to scan. Add
            your comics folder as a root folder in{' '}
            <Link to="/settings/media-management">Media Management settings</Link>{' '}
            first, then import your existing library from here.
          </p>
        )}

        {!unconfigured && rootFolders.data && (
          <>
            <div className={styles.scanBar}>
              <label className={styles.formRow}>
                <span>Root Folder</span>
                <select
                  aria-label="Root folder"
                  value={rootId ?? ''}
                  onChange={(e) => setPickedRootId(Number(e.target.value))}
                >
                  {rootFolders.data.map((folder) => (
                    <option key={folder.id} value={folder.id}>
                      {folder.path}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className={styles.scanButton}
                data-testid="li-scan"
                disabled={rootId === null || scan.isPending || scanCommand.running}
                onClick={startScan}
              >
                {scanCommand.running ? 'Scanning…' : 'Scan'}
              </button>
              {scanCommand.status && (
                <span
                  role="status"
                  className={styles.commandChip}
                  data-testid="li-scan-status"
                >
                  Scan: {scanCommand.status}
                </span>
              )}
            </div>
            {scan.isError && (
              <p role="alert" className={styles.errorNote}>
                Scan failed: {scan.error.message}
              </p>
            )}

            {groupsQuery.isLoading && (
              <p className={styles.stateNote}>Loading staged scan results…</p>
            )}
            {groupsQuery.isError && (
              <p role="alert" className={styles.errorNote}>
                Could not load staged scan results: {groupsQuery.error.message}
              </p>
            )}

            {/* Empty states are explicit — never a blank results area. */}
            {groupsQuery.data && groups.length === 0 && rootId !== null && (
              scannedRoots.has(rootId) ? (
                <p className={styles.stateNote} data-testid="li-empty-mapped">
                  The scan found nothing to import — everything under{' '}
                  {root?.path ?? 'this root folder'} is already mapped to a
                  series in the library.
                </p>
              ) : (
                <p className={styles.stateNote} data-testid="li-empty-unscanned">
                  Nothing is staged for this root folder yet. Run a scan to
                  find unmapped series folders.
                </p>
              )
            )}

            {groups.length > 0 && (
              <div className={styles.groupList}>
                {groups.map((group) => (
                  <GroupCard
                    key={group.id}
                    group={group}
                    selectable={isSelectable(group)}
                    checked={selected.has(group.id) && isSelectable(group)}
                    busy={busy}
                    onToggle={() => toggleSelected(group.id)}
                    onPatch={(patch) =>
                      patchGroup.mutate({ groupId: group.id, patch })
                    }
                  />
                ))}
              </div>
            )}
            {patchGroup.isError && (
              <p role="alert" className={styles.errorNote}>
                Update failed: {patchGroup.error.message}
              </p>
            )}

            {picked.length > 0 && root && (
              <BatchOptionsPanel
                rootPath={root.path}
                count={picked.length}
                busy={execute.isPending || executeCommand.running}
                status={executeCommand.status}
                error={execute.isError ? execute.error.message : null}
                onImport={(addOptions) =>
                  execute.mutate(
                    { groupIds: picked.map((group) => group.id), addOptions },
                    { onSuccess: (cmd) => executeCommand.start(cmd.id) },
                  )
                }
              />
            )}
          </>
        )}
      </div>
    </>
  );
}

/** The staging-state / outcome chip for one group. Blocked reasons verbatim. */
function GroupBadge({
  group,
  folderName,
}: {
  group: LibraryImportGroup;
  folderName: string;
}) {
  if (group.state === 'imported') {
    return <span className={`${styles.chip} ${styles.chipGood}`}>Imported</span>;
  }
  if (group.rejections.length > 0) {
    // A selected group the execute command could not import: its verbatim
    // reasons render through the shared popover (manual-import presentation).
    return (
      <ReasonsPopover
        reasons={group.rejections}
        label={`${folderName} — show reasons`}
        chipClassName={`${styles.chip} ${styles.chipBlocked}`}
        chipContent={<>! Blocked</>}
        listTestId={`ft-li-rejections-${folderName}`}
      />
    );
  }
  if (group.state === 'skipped') {
    return <span className={styles.chip}>Skipped</span>;
  }
  if (group.state === 'confirmed') {
    return (
      <span className={`${styles.chip} ${styles.chipAccent}`}>Confirmed</span>
    );
  }
  if (group.state === 'no_match' || group.proposedCvVolumeId === null) {
    return <span className={`${styles.chip} ${styles.chipWarn}`}>No match</span>;
  }
  return <span className={styles.chip}>Proposed</span>;
}

function GroupCard({
  group,
  selectable,
  checked,
  busy,
  onToggle,
  onPatch,
}: {
  group: LibraryImportGroup;
  selectable: boolean;
  checked: boolean;
  busy: boolean;
  onToggle: () => void;
  onPatch: (patch: LibraryImportGroupPatch) => void;
}) {
  const [searching, setSearching] = useState(false);
  const folderName = group.folder.split('/').filter(Boolean).pop() ?? group.folder;
  // A proposal card renders exactly when the group carries a match (the same
  // condition that makes it selectable); a no_match group — or a proposed
  // group whose lazy proposal never arrived — renders the explicit state.
  const hasMatch = isSelectable(group);
  const settled = group.state === 'imported' || group.state === 'skipped';

  return (
    <div className={styles.groupCard} data-testid={`li-group-${group.id}`}>
      <div className={styles.groupHeader}>
        <input
          type="checkbox"
          checked={checked}
          disabled={!selectable || busy}
          aria-label={`Select ${folderName}`}
          onChange={onToggle}
        />
        <span className={styles.folderName}>{folderName}</span>
        <span className={styles.folderPath}>{group.folder}</span>
        <span className={styles.chip}>
          {group.files.length} file{group.files.length === 1 ? '' : 's'}
        </span>
        <span className={styles.chip}>
          Confidence {Math.round(group.confidence * 100)}%
        </span>
        <GroupBadge group={group} folderName={folderName} />
      </div>

      {hasMatch && (
        <div className={styles.proposal}>
          <Poster
            initial={(group.name ?? '?').charAt(0)}
            src={group.imageUrl}
            alt={`${group.name ?? 'volume'} cover`}
            frameClassName={styles.posterFrame}
            fallbackClassName={styles.posterFallback}
            lazy
          />
          <span className={styles.proposalInfo}>
            <span className={styles.proposalTitle}>
              {group.name ?? 'Unnamed volume'}
              {group.startYear !== null && (
                <span className={styles.proposalYear}> ({group.startYear})</span>
              )}
            </span>
            {group.publisher && (
              <span className={styles.publisher}>{group.publisher}</span>
            )}
          </span>
        </div>
      )}

      {!hasMatch && !settled && (
        <p className={styles.noMatch} data-testid={`li-no-match-${group.id}`}>
          No plausible ComicVine match — search and pick a volume before this
          folder can be imported.
        </p>
      )}

      {!settled && (
        <div className={styles.groupActions}>
          {group.state === 'proposed' && hasMatch && (
            <button
              type="button"
              className={`${styles.btn} ${styles.btnPrimary}`}
              disabled={busy}
              onClick={() => onPatch({ action: 'confirm' })}
            >
              Confirm match
            </button>
          )}
          <button
            type="button"
            className={styles.btn}
            disabled={busy}
            onClick={() => setSearching((s) => !s)}
          >
            {searching
              ? 'Cancel search'
              : hasMatch
                ? 'Change match'
                : 'Search ComicVine'}
          </button>
          <button
            type="button"
            className={styles.btn}
            disabled={busy}
            onClick={() => onPatch({ action: 'skip' })}
          >
            Skip
          </button>
        </div>
      )}

      {searching && !settled && (
        <GroupLookup
          folderName={folderName}
          busy={busy}
          onPick={(cvVolumeId) => {
            onPatch({ cvVolumeId });
            setSearching(false);
          }}
        />
      )}
    </div>
  );
}

/**
 * Inline ComicVine lookup for correcting/setting one group's match. Reuses the
 * add screen's lookup machinery wholesale: the same envelope classification
 * (credential / degraded / capped / incomplete / empty via lookupOutcomeNote),
 * the same term normalization, and the same explicit same-term retry after a
 * retryable outcome. Picking a candidate PATCHes the override.
 */
function GroupLookup({
  folderName,
  busy,
  onPick,
}: {
  folderName: string;
  busy: boolean;
  onPick: (cvVolumeId: number) => void;
}) {
  const [input, setInput] = useState('');
  const [term, setTerm] = useState('');
  const lookup = useLookup(term);

  // An error must never leak stale candidates from a previous outcome.
  const results = lookup.isError ? undefined : lookup.data;
  const note = lookupOutcomeNote(lookup.isError, lookup.error, results, term);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const next = normalizeLookupTerm(input);
    const retryable =
      lookup.isError ||
      (lookup.data !== undefined &&
        (!lookup.data.complete || lookup.data.truncated));
    if (next === term && retryable) {
      void lookup.refetch();
    }
    setTerm(next);
  };

  return (
    <div className={styles.lookup} data-testid={`li-lookup-${folderName}`}>
      <form className={styles.lookupForm} onSubmit={submit} role="search">
        <input
          className={styles.lookupInput}
          type="search"
          aria-label={`Search ComicVine for ${folderName}`}
          placeholder="Series name, or a ComicVine volume URL / 4050-XXXX id"
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <button type="submit" className={styles.btn}>
          Search
        </button>
      </form>

      {lookup.isLoading && (
        <p className={styles.stateNote}>Searching ComicVine…</p>
      )}
      {note?.tone === 'error' && (
        <p className={styles.errorNote} role="alert">
          {note.text}
        </p>
      )}
      {note?.tone === 'status' && (
        <p className={styles.stateNote} role="status">
          {note.text}
        </p>
      )}
      {note?.tone === 'plain' && <p className={styles.stateNote}>{note.text}</p>}

      {results && results.records.length > 0 && (
        <div className={styles.lookupResults}>
          {results.records.map((candidate) => (
            <button
              key={candidate.cv_volume_id}
              type="button"
              className={styles.lookupCandidate}
              data-testid={`li-candidate-${candidate.cv_volume_id}`}
              disabled={busy}
              onClick={() => onPick(candidate.cv_volume_id)}
            >
              <span className={styles.proposalTitle}>
                {candidate.name ?? 'Unnamed volume'}
                {candidate.start_year !== null && (
                  <span className={styles.proposalYear}>
                    {' '}
                    ({candidate.start_year})
                  </span>
                )}
              </span>
              {candidate.publisher && (
                <span className={styles.publisher}>{candidate.publisher}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Batch add options for the selected groups (AddOptionsPanel adapted): the
 * root folder is FIXED to the scanned root (in-place import pins series
 * there), format profile + monitor strategy + search-on-add apply to every
 * group in the batch.
 */
function BatchOptionsPanel({
  rootPath,
  count,
  busy,
  status,
  error,
  onImport,
}: {
  rootPath: string;
  count: number;
  busy: boolean;
  status: string | null;
  error: string | null;
  onImport: (addOptions: {
    formatProfileId: number | null;
    monitorStrategy: string;
    searchOnAdd: boolean;
  }) => void;
}) {
  const formatProfiles = useFormatProfiles();
  // null = not chosen yet -> default to the first entry once the list loads.
  const [formatProfileId, setFormatProfileId] = useState<number | null>(null);
  const [monitorStrategy, setMonitorStrategy] = useState('all');
  const [searchOnAdd, setSearchOnAdd] = useState(false);
  const selectedProfileId =
    formatProfileId ?? formatProfiles.data?.[0]?.id ?? null;

  return (
    <div className={styles.batchPanel} data-testid="li-batch-panel">
      <div className={styles.formRow}>
        <span>Root Folder</span>
        <span className={styles.fixedValue} data-testid="li-batch-root">
          {rootPath}
        </span>
      </div>
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
      {status && (
        <span
          role="status"
          className={styles.commandChip}
          data-testid="li-import-status"
        >
          Import: {status}
        </span>
      )}
      {error && (
        <p className={styles.errorNote} role="alert">
          Import failed: {error}
        </p>
      )}
      <button
        type="button"
        className={styles.importButton}
        data-testid="li-import-confirm"
        disabled={busy}
        onClick={() =>
          onImport({
            formatProfileId: selectedProfileId,
            monitorStrategy,
            searchOnAdd,
          })
        }
      >
        {busy ? 'Importing…' : `Import ${count} selected`}
      </button>
    </div>
  );
}
