import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Toolbar } from '../../components/Toolbar';
import { PageControls } from '../../components/PageControls';
import {
  useBlocklistPage,
  useBulkRemoveBlocklist,
  useRemoveBlocklistItem,
} from '../../api/hooks';
import type { BlocklistRecord } from '../../api/types';
import { formatDate } from '../../lib/format';
import styles from './BlocklistScreen.module.css';

/**
 * Activity: Blocklist (FRG-UI-017) — paged banned releases over
 * GET /api/v1/blocklist with the ban reason VERBATIM. Removing an entry
 * (per-row DELETE or bulk POST /blocklist/delete) makes the release grabbable
 * again; a mid-batch failure reports exactly which removals did not happen
 * (the response's `missing` ids).
 */

function banDate(record: BlocklistRecord): string | null {
  return record.date ?? null;
}

export function BlocklistScreen() {
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set());
  const [notice, setNotice] = useState<string | null>(null);
  const { data, isLoading, isError } = useBlocklistPage(page, setPage);
  const removeOne = useRemoveBlocklistItem();
  const bulkRemove = useBulkRemoveBlocklist();

  const records = data?.records ?? [];
  const selectedIds = records.filter((r) => selected.has(r.id)).map((r) => r.id);
  const allSelected = records.length > 0 && selectedIds.length === records.length;

  const toggleSelected = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  const toggleSelectAll = () => {
    setSelected(allSelected ? new Set() : new Set(records.map((r) => r.id)));
  };

  const removeSelected = () => {
    if (selectedIds.length === 0) return;
    setNotice(null);
    bulkRemove.mutate(selectedIds, {
      onSuccess: (result) => {
        setSelected(new Set());
        if (result.missing.length > 0) {
          setNotice(
            `Removed ${result.deleted.length} of ${selectedIds.length} entries. ` +
              `Could not remove: ${result.missing.join(', ')}.`,
          );
        }
      },
      onError: (error) => setNotice(`Bulk removal failed: ${error.message}`),
    });
  };

  return (
    <>
      <Toolbar
        title="Blocklist"
        actions={
          <span className={styles.toolbarActions}>
            <button
              type="button"
              className={styles.btn}
              disabled={selectedIds.length === 0 || bulkRemove.isPending}
              onClick={removeSelected}
            >
              Remove Selected
            </button>
          </span>
        }
      />
      <div>
        {notice && (
          <p className={styles.notice} role="alert">
            {notice}
          </p>
        )}
        {isLoading && <p className={styles.state}>Loading blocklist…</p>}
        {isError && <p className={styles.state}>Could not load the blocklist.</p>}
        {!isLoading && !isError && records.length === 0 && (
          <p className={styles.state}>The blocklist is empty.</p>
        )}
        {records.length > 0 && (
          <table className={styles.table}>
            <thead>
              <tr>
                <th className={styles.selectCol}>
                  <input
                    type="checkbox"
                    aria-label="Select all blocklist entries"
                    checked={allSelected}
                    onChange={toggleSelectAll}
                  />
                </th>
                <th>Source Title</th>
                <th>Series</th>
                <th>Issue</th>
                <th>Indexer</th>
                <th>Date</th>
                <th>Reason</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {records.map((record) => (
                <tr key={record.id} data-testid={`blocklist-row-${record.id}`}>
                  <td className={styles.selectCol}>
                    <input
                      type="checkbox"
                      aria-label={`Select ${record.sourceTitle}`}
                      checked={selected.has(record.id)}
                      onChange={() => toggleSelected(record.id)}
                    />
                  </td>
                  <td>{record.sourceTitle}</td>
                  <td>
                    {record.series ? (
                      <Link
                        className={styles.seriesLink}
                        to={`/series/${record.series.id}`}
                      >
                        {record.series.title}
                      </Link>
                    ) : (
                      '—'
                    )}
                  </td>
                  {/* Verbatim string issue number — never coerced. */}
                  <td className={styles.numeric}>
                    {record.issue?.issueNumber != null
                      ? `#${record.issue.issueNumber}`
                      : '—'}
                  </td>
                  <td className={styles.muted}>
                    {record.indexer ?? '—'}
                    {record.protocol ? ` · ${record.protocol}` : ''}
                  </td>
                  <td className={styles.numeric}>{formatDate(banDate(record))}</td>
                  {/* The ban reason, verbatim — never paraphrased. */}
                  <td className={styles.reasonCell}>{record.message ?? '—'}</td>
                  <td className={styles.actionsCell}>
                    <button
                      type="button"
                      className={styles.btn}
                      aria-label={`Remove ${record.sourceTitle}`}
                      disabled={removeOne.isPending}
                      onClick={() => removeOne.mutate(record.id)}
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {data && (
          <PageControls
            page={data.page}
            totalRecords={data.totalRecords}
            pageSize={data.pageSize}
            onPageChange={setPage}
          />
        )}
      </div>
    </>
  );
}
