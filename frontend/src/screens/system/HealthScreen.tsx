import { Toolbar } from '../../components/Toolbar';
import { useHealthWarnings, useSystemHealth } from '../../api/hooks';
import type { ComponentHealthState, HealthStateType } from '../../api/types';
import { formatEta } from '../../lib/format';
import styles from './System.module.css';

/**
 * System — Health (FRG-UI-016 / FRG-NFR-011). Renders GET /api/v1/health (the
 * actionable warnings list, with remediation hints) and GET
 * /api/v1/system/health (the full per-component table — ok / degraded with
 * its disabled-until countdown / error). Both queries poll (design decision
 * 7), so a component that recovers clears on the next poll without a manual
 * refresh or restart. An empty warnings list renders an explicit "all
 * healthy" state, distinct from the loading/error states.
 */

const WARNING_CHIP_CLASS: Record<HealthStateType, string> = {
  ok: styles.chipOk,
  warning: styles.chipWarning,
  error: styles.chipError,
};

const COMPONENT_CHIP_CLASS: Record<ComponentHealthState, string> = {
  ok: styles.chipOk,
  degraded: styles.chipWarning,
  error: styles.chipError,
};

const COMPONENT_STATE_LABEL: Record<ComponentHealthState, string> = {
  ok: 'OK',
  degraded: 'Degraded',
  error: 'Error',
};

export function HealthScreen() {
  const warningsQuery = useHealthWarnings();
  const componentsQuery = useSystemHealth();

  const isLoading = warningsQuery.isLoading || componentsQuery.isLoading;
  const isError = warningsQuery.isError || componentsQuery.isError;
  const warnings = warningsQuery.data ?? [];
  const components = componentsQuery.data ?? [];

  return (
    <>
      <Toolbar title="System — Health" />
      <div className={styles.page}>
        {isLoading && <p className={styles.state}>Loading system health…</p>}
        {isError && <p className={styles.state}>Could not load system health.</p>}

        {!isLoading && !isError && (
          <>
            <section className={styles.section}>
              <h2 className={styles.sectionHeading}>Warnings</h2>
              {warnings.length === 0 ? (
                <p className={styles.allHealthy} data-testid="health-all-healthy">
                  All healthy — no active warnings.
                </p>
              ) : (
                <ul className={styles.warningList} data-testid="health-warnings">
                  {warnings.map((item) => (
                    <li
                      key={item.source}
                      className={styles.warningRow}
                      data-testid={`health-warning-${item.source}`}
                    >
                      <span
                        className={`${styles.chip} ${WARNING_CHIP_CLASS[item.type]}`}
                      >
                        {item.type}
                      </span>
                      <div className={styles.warningBody}>
                        <span className={styles.warningSource}>{item.source}</span>
                        <span className={styles.warningMessage}>{item.message}</span>
                        {item.remediationHint && (
                          <span className={styles.warningHint}>
                            {item.remediationHint}
                          </span>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className={styles.section}>
              <h2 className={styles.sectionHeading}>Components</h2>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Component</th>
                    <th>State</th>
                    <th>Last Success</th>
                    <th>Last Failure</th>
                    <th>Disabled Until</th>
                  </tr>
                </thead>
                <tbody>
                  {components.map((component) => (
                    <tr
                      key={component.component}
                      data-testid={`health-component-${component.component}`}
                    >
                      <td>{component.component}</td>
                      <td>
                        <span
                          className={`${styles.chip} ${COMPONENT_CHIP_CLASS[component.state]}`}
                        >
                          {COMPONENT_STATE_LABEL[component.state]}
                        </span>
                      </td>
                      <td className={styles.muted}>{component.last_success ?? '—'}</td>
                      <td className={styles.muted}>{component.last_failure ?? '—'}</td>
                      <td className={styles.muted}>
                        {component.disabled_until
                          ? formatEta(component.disabled_until)
                          : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          </>
        )}
      </div>
    </>
  );
}
