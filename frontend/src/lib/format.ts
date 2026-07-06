/**
 * The single presentation-only formatting module (FRG-UI-006/007) — no domain
 * logic. All screens import from here; there is no second `formatBytes`.
 */

const BYTE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB'] as const;

/**
 * Human-readable byte size ("40.1 MB"). null/undefined and non-finite/negative
 * inputs render as an em dash; 0 renders as "0 B".
 */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return '—';
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < BYTE_UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const rounded = unit === 0 ? String(value) : value.toFixed(1);
  return `${rounded} ${BYTE_UNITS[unit]}`;
}

/** Age in seconds -> Sonarr-style short age: "3h", "2d", "1.5y". */
export function formatAge(ageSeconds: number | null | undefined): string {
  if (ageSeconds == null || Number.isNaN(ageSeconds) || ageSeconds < 0) {
    return '—';
  }
  const days = ageSeconds / 86_400;
  if (days < 1) return `${Math.max(1, Math.round(ageSeconds / 3_600))}h`;
  if (days < 365) return `${Math.round(days)}d`;
  return `${(days / 365).toFixed(1)}y`;
}

/** ISO timestamp -> "in 4m" / "in 2h 05m"; past or null -> em dash. */
export function formatEta(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return '—';
  const target = Date.parse(iso);
  if (Number.isNaN(target) || target <= now) return '—';
  const totalMinutes = Math.ceil((target - now) / 60_000);
  if (totalMinutes < 60) return `in ${totalMinutes}m`;
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return `in ${hours}h ${String(minutes).padStart(2, '0')}m`;
}

/** ISO date/datetime string -> "Jan 5 2026"; null-safe. */
export function formatDate(iso: string | null): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

/** Uppercase file-format label from a file path ("....cbz" -> "CBZ"). */
export function fileFormat(path: string): string {
  const dot = path.lastIndexOf('.');
  return dot === -1 ? '' : path.slice(dot + 1).toUpperCase();
}
