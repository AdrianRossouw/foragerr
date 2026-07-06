import { Toolbar } from '../../components/Toolbar';
import { useSystemStatus } from '../../api/hooks';
import { formatAge } from '../../lib/format';
import styles from './System.module.css';

/**
 * System — Status (FRG-UI-016). Renders GET /api/v1/system/status: the
 * application version/build info, the managed `/config` paths, and runtime
 * info. Deliberately renders ONLY the fields the resource carries — the
 * backend contract (FRG-API-014) never includes a provider key or other
 * secret, so there is no field to filter out here.
 */
export function StatusScreen() {
  const { data, isLoading, isError } = useSystemStatus();

  return (
    <>
      <Toolbar title="System — Status" />
      <div className={styles.page}>
        {isLoading && <p className={styles.state}>Loading system status…</p>}
        {isError && <p className={styles.state}>Could not load system status.</p>}
        {data && (
          <div data-testid="system-status">
            <section className={styles.section}>
              <h2 className={styles.sectionHeading}>Version</h2>
              <dl className={styles.factList}>
                <Fact label="Version" value={data.version} />
                <Fact label="Commit" value={data.commit} />
                <Fact label="Build Date" value={data.build_date} />
              </dl>
            </section>

            <section className={styles.section}>
              <h2 className={styles.sectionHeading}>Paths</h2>
              <dl className={styles.factList}>
                <Fact label="Config Directory" value={data.config_dir} />
                <Fact label="Database Path" value={data.db_path} />
                <Fact label="Backups Directory" value={data.backups_dir} />
                <Fact label="Root Folders" value={String(data.root_folder_count)} />
              </dl>
            </section>

            <section className={styles.section}>
              <h2 className={styles.sectionHeading}>Runtime</h2>
              <dl className={styles.factList}>
                <Fact label="Uptime" value={formatAge(data.uptime_seconds)} />
                <Fact label="Python" value={data.python_version} />
                <Fact label="OS" value={data.os} />
              </dl>
            </section>
          </div>
        )}
      </div>
    </>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.factRow} data-testid={`status-fact-${label}`}>
      <dt className={styles.factLabel}>{label}</dt>
      <dd className={styles.factValue}>{value}</dd>
    </div>
  );
}
