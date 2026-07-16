import { useEffect, useState } from 'react';
import { Toolbar } from '../../components/Toolbar';
import { useHealthWarnings, useSystemHealth } from '../../api/hooks';
import type { ComponentHealthState, HealthStateType } from '../../api/types';
import { formatDate, formatEta } from '../../lib/format';
import styles from './System.module.css';

/**
 * System — Health (FRG-UI-016 / FRG-NFR-011). Renders GET /api/v1/health (the
 * actionable warnings list, with remediation hints) and GET
 * /api/v1/system/health (the full per-component table — ok / degraded with
 * its disabled-until countdown / error). Both queries poll (design decision
 * 7), so a component that recovers clears on the next poll without a manual
 * refresh or restart. An empty warnings list renders an explicit "all
 * healthy" state, distinct from the loading/error states.
 *
 * A sustained poll failure does NOT blank a screen that already has retained
 * (stale) data — react-query keeps the last-good `data` around across a
 * failed refetch, so the full "Could not load" state is reserved for when
 * there is genuinely nothing to show yet; otherwise the stale table stays up
 * with a dismissable banner (FRG-UI-016).
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
  // Retained (possibly stale) data from either query — react-query keeps the
  // last successful result across a failed background refetch.
  const hasData = warningsQuery.data !== undefined && componentsQuery.data !== undefined;
  const warnings = warningsQuery.data ?? [];
  const components = componentsQuery.data ?? [];

  const [staleBannerDismissed, setStaleBannerDismissed] = useState(false);
  // Reset the dismissal once the poll recovers, so a LATER failure shows the
  // banner again instead of staying silently dismissed forever.
  useEffect(() => {
    if (!isError) setStaleBannerDismissed(false);
  }, [isError]);

  return (
    <>
      <Toolbar title="System — Health" />
      <div className={styles.page}>
        {isLoading && <p className={styles.state}>Loading system health…</p>}
        {/* The full error state is reserved for "nothing to show at all" — a
            sustained poll failure with data already on screen renders that
            (possibly stale) data instead, with the banner below. */}
        {isError && !hasData && (
          <p className={styles.state}>Could not load system health.</p>
        )}
        {isError && hasData && !staleBannerDismissed && (
          <p className={styles.staleBanner} role="status" data-testid="health-stale-banner">
            Health data may be stale — last update failed.
            <button
              type="button"
              className={styles.staleBannerDismiss}
              onClick={() => setStaleBannerDismissed(true)}
            >
              Dismiss
            </button>
          </p>
        )}

        {hasData && (
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
              {/* Focusable, labelled scroll region: the wide component table
                  overflows horizontally on narrow viewports, and a scrollable
                  region with no focusable descendants must be keyboard-reachable
                  (axe scrollable-region-focusable, FRG-UI-038). */}
              <div
                className={styles.tableScroll}
                tabIndex={0}
                role="region"
                aria-label="Health components"
                data-testid="health-components-scroll"
              >
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
                      <td>
                        <div className={styles.componentLabel}>{component.label}</div>
                        <div className={styles.componentId}>{component.component}</div>
                      </td>
                      <td>
                        <span
                          className={`${styles.chip} ${COMPONENT_CHIP_CLASS[component.state]}`}
                        >
                          {COMPONENT_STATE_LABEL[component.state]}
                        </span>
                      </td>
                      <td className={styles.muted}>{formatDate(component.last_success)}</td>
                      <td className={styles.muted}>{formatDate(component.last_failure)}</td>
                      <td className={styles.muted}>
                        {component.disabled_until
                          ? formatEta(component.disabled_until)
                          : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            </section>
          </>
        )}
      </div>
    </>
  );
}
