import { useSystemHealth } from '../api/hooks';
import type {
  ComicVineBudgetBucket,
  ComicVineBudgetDetail,
  SystemHealthComponent,
} from '../api/types';
import styles from './ComicVineBudget.module.css';

/**
 * The ComicVine budget meter (FRG-UI-040), rendered from the health surface's
 * structured detail (FRG-API-025) — no endpoint of its own.
 *
 * One ComicVine API key is a scarce, shared resource: a rolling-hour ceiling
 * per resource path, of which background (batch) work may spend a configured
 * share while the remainder stays reserved for whatever the operator is doing
 * right now (FRG-META-022). Until this, those numbers existed only inside the
 * gate and surfaced as a warning AFTER the wall. Two surfaces read them here:
 *
 * - `ComicVineBudgetMeter` — the full per-bucket meter beside the key in
 *   Settings → General, where an operator goes to understand their key.
 * - `ComicVineBudgetChip` — a compact indicator on the Sources review bar,
 *   which renders ONLY when a bucket is at or above the warning fraction. That
 *   quiet-by-default rule is the point: a meter that is always on screen is
 *   wallpaper, and the review queue is where an operator spends budget without
 *   thinking about it.
 *
 * Both read the SAME polled `useSystemHealth` query the Health screen uses, so
 * they refresh on its cadence, cost no extra request, and can never disagree
 * with the Health screen about the state of the budget.
 */

/**
 * Fraction of a path ceiling at which a bucket is "hot" — mirrors the
 * backend's `BUDGET_WARNING_FRACTION`. The backend may report a bucket BELOW
 * this (e.g. a paused batch lane at 70%), which the full meter shows; the
 * compact chip applies this threshold so the review screen stays quiet until
 * the ceiling itself is in question (FRG-UI-040 scenario 2).
 */
export const BUDGET_WARNING_FRACTION = 0.8;

/** The ComicVine component's budget detail from a health payload, if any. */
export function comicVineBudget(
  components: SystemHealthComponent[] | undefined,
): ComicVineBudgetDetail | null {
  const component = components?.find((c) => c.component === 'comicvine');
  const detail = component?.detail;
  return detail && detail.buckets.length > 0 ? detail : null;
}

/** The polled budget detail (`null` when there is nothing to report). */
export function useComicVineBudget(): ComicVineBudgetDetail | null {
  const health = useSystemHealth();
  return comicVineBudget(health.data);
}

/** Buckets at or above the warning fraction of their ceiling. */
export function hotBuckets(
  detail: ComicVineBudgetDetail | null,
): ComicVineBudgetBucket[] {
  if (!detail) return [];
  return detail.buckets.filter(
    (b) => b.ceiling > 0 && b.used / b.ceiling >= BUDGET_WARNING_FRACTION,
  );
}

/** Seconds until capacity returns -> "resumes in ~4 min" (blank when open). */
function resumeNote(seconds: number): string {
  if (!seconds || seconds <= 0) return '';
  const minutes = Math.max(1, Math.round(seconds / 60));
  return `resumes in ~${minutes} min`;
}

function pct(used: number, ceiling: number): number {
  if (ceiling <= 0) return 0;
  return Math.min(100, Math.round((used / ceiling) * 100));
}

/** Whether this bucket's background lane has spent its whole share. */
function batchPaused(bucket: ComicVineBudgetBucket): boolean {
  return (
    bucket.batch_ceiling != null &&
    bucket.batch_used != null &&
    bucket.batch_used >= bucket.batch_ceiling
  );
}

function BucketRow({ bucket }: { bucket: ComicVineBudgetBucket }) {
  const exhausted = bucket.used >= bucket.ceiling;
  const paused = batchPaused(bucket);
  const resume = resumeNote(bucket.resume_seconds);
  // Where the batch lane's share ends, drawn on the same track as the usage
  // fill: the gap to its right IS the interactive reserve, which is the one
  // thing the raw numbers do not make obvious.
  const batchMark =
    bucket.batch_ceiling != null && bucket.ceiling > 0
      ? Math.min(100, (bucket.batch_ceiling / bucket.ceiling) * 100)
      : null;
  return (
    <li className={styles.row} data-testid={`cv-budget-bucket-${bucket.bucket}`}>
      <div className={styles.rowHead}>
        <code className={styles.bucket}>{bucket.bucket}</code>
        <span className={styles.usage}>
          {bucket.used} / {bucket.ceiling}
        </span>
      </div>
      <div
        className={styles.track}
        data-exhausted={exhausted}
        role="meter"
        aria-valuenow={bucket.used}
        aria-valuemin={0}
        aria-valuemax={bucket.ceiling}
        aria-label={`ComicVine hourly requests used on ${bucket.bucket}`}
      >
        <span
          className={styles.fill}
          style={{ width: `${pct(bucket.used, bucket.ceiling)}%` }}
          aria-hidden
        />
        {batchMark != null && (
          <span
            className={styles.batchMark}
            style={{ left: `${batchMark}%` }}
            aria-hidden
          />
        )}
      </div>
      <div className={styles.rowNote}>
        {bucket.batch_ceiling != null && bucket.batch_used != null && (
          <span data-testid={`cv-budget-batch-${bucket.bucket}`}>
            background {bucket.batch_used} / {bucket.batch_ceiling}
            {paused ? ' — paused, interactive reserve remains' : ''}
          </span>
        )}
        {resume && <span className={styles.resume}>{resume}</span>}
      </div>
    </li>
  );
}

/**
 * The full meter (Settings → General). Renders every reported bucket, or a
 * one-line all-clear when the backend has nothing to report — the operator
 * came here to find out, so "nothing is under pressure" is an answer.
 */
export function ComicVineBudgetMeter() {
  const detail = useComicVineBudget();
  return (
    <div className={styles.meter} data-testid="cv-budget-meter">
      <h3 className={styles.heading}>Hourly request budget</h3>
      {detail === null ? (
        <p className={styles.quiet} data-testid="cv-budget-quiet">
          No ComicVine path is near its hourly limit. Usage appears here as a
          path approaches its ceiling — background work pauses first, so
          searches you are waiting on keep working.
        </p>
      ) : (
        <>
          <ul className={styles.list}>
            {detail.buckets.map((bucket) => (
              <BucketRow key={bucket.bucket} bucket={bucket} />
            ))}
          </ul>
          {detail.exhausted && (
            <p className={styles.exhaustedNote} role="status">
              A path is at its ceiling — requests on it are deferred until the
              rolling hour clears. Nothing is lost; deferred work resumes by
              itself.
            </p>
          )}
        </>
      )}
    </div>
  );
}

/**
 * The compact indicator (Sources review bar). Renders NOTHING unless a bucket
 * is at or above the warning fraction (FRG-UI-040): quiet when there is nothing
 * to say, present exactly when the queue an operator is working is about to
 * stop being served.
 */
export function ComicVineBudgetChip() {
  const detail = useComicVineBudget();
  const hot = hotBuckets(detail);
  if (hot.length === 0) return null;
  const worst = hot[0];
  const resume = resumeNote(worst.resume_seconds);
  const extra = hot.length > 1 ? ` +${hot.length - 1}` : '';
  return (
    <span className={styles.chip} data-testid="cv-budget-chip" role="status">
      <i className="fa-solid fa-gauge-high" aria-hidden />{' '}
      ComicVine {worst.bucket} {worst.used}/{worst.ceiling}
      {extra}
      {resume ? ` · ${resume}` : batchPaused(worst) ? ' · background paused' : ''}
    </span>
  );
}
