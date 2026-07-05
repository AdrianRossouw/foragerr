/* Presentation-only formatting helpers (FRG-UI-006/007). */

const BYTE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB'] as const;

/** 42_000_000 -> "40.1 MB"; null/unknown -> em dash. */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || Number.isNaN(bytes) || bytes < 0) return '—';
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
