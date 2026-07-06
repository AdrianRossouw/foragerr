import { useQueryClient } from '@tanstack/react-query';
import { Toolbar } from '../../components/Toolbar';
import {
  useForceRunTask,
  useSystemTasks,
  useWatchedCommand,
} from '../../api/hooks';
import { queryKeys } from '../../api/queryKeys';
import type { ScheduledTaskResource } from '../../api/types';
import { formatAge, formatDate, formatEta } from '../../lib/format';
import styles from './System.module.css';

/**
 * System — Tasks (FRG-UI-016). Renders GET /api/v1/system/task: the
 * scheduled-task table (interval, last/next run) with a per-task force-run
 * button. The `backup-database` row's button reads "Back up now" — same
 * `POST /api/v1/system/task/{name}` action (FRG-SCHED-007 via force_run), just
 * a more prominent label/style. Each row watches its own force-run to
 * terminal via `useWatchedCommand`, then re-invalidates the task list so
 * last-run/next-run reflect the finished run.
 */
export function TasksScreen() {
  const { data, isLoading, isError } = useSystemTasks();
  const tasks = data ?? [];

  return (
    <>
      <Toolbar title="System — Tasks" />
      <div className={styles.page}>
        {isLoading && <p className={styles.state}>Loading scheduled tasks…</p>}
        {isError && <p className={styles.state}>Could not load scheduled tasks.</p>}
        {!isLoading && !isError && tasks.length === 0 && (
          <p className={styles.state}>No scheduled tasks are registered.</p>
        )}
        {tasks.length > 0 && (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Task</th>
                <th>Interval</th>
                <th>Last Run</th>
                <th>Next Run</th>
                <th aria-label="Status" />
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <TaskRow key={task.name} task={task} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

const BACKUP_TASK_NAME = 'backup-database';

function TaskRow({ task }: { task: ScheduledTaskResource }) {
  const queryClient = useQueryClient();
  const forceRun = useForceRunTask();
  const isBackup = task.name === BACKUP_TASK_NAME;

  // One watcher per row: each task's force-run tracks its OWN command to
  // terminal (unlike the shared-watcher screens elsewhere) so two different
  // tasks force-run in quick succession never clobber each other's chip.
  const command = useWatchedCommand(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.system.tasks() });
  });

  const onRun = () => {
    forceRun.mutate(task.name, {
      onSuccess: (record) => command.start(record.id),
    });
  };

  return (
    <tr data-testid={`task-row-${task.name}`}>
      <td>{task.label}</td>
      <td className={styles.muted}>Every {formatAge(task.interval_seconds)}</td>
      <td className={styles.muted}>{formatDate(task.last_run)}</td>
      <td className={styles.muted}>{formatEta(task.next_run)}</td>
      <td>
        {command.status && (
          <span
            className={styles.commandChip}
            data-testid={`task-status-${task.name}`}
          >
            {command.status}
          </span>
        )}
      </td>
      <td className={styles.actionsCell}>
        <button
          type="button"
          className={isBackup ? `${styles.btn} ${styles.btnPrimary}` : styles.btn}
          disabled={command.running || forceRun.isPending}
          onClick={onRun}
        >
          {command.running ? 'Running…' : isBackup ? 'Back up now' : 'Run Now'}
        </button>
      </td>
    </tr>
  );
}
