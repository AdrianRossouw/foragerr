import styles from './InitialsAvatar.module.css';

/**
 * Deterministic initials avatar (FRG-UI-027/028, design decision 3). A green
 * gradient disc (the `--color-avatar-gradient-*` tokens) behind the creator's
 * initials — foragerr shows NO person images, so this is the only creator
 * likeness. The initials are derived purely from the name (same name → same
 * two letters every render): first letters of the first two words, or the first
 * two letters of a single-word name.
 */
export function initialsFromName(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return '?';
  if (words.length === 1) {
    return words[0].slice(0, 2).toUpperCase();
  }
  return (words[0][0] + words[1][0]).toUpperCase();
}

export function InitialsAvatar({
  name,
  size = 46,
  className,
}: {
  name: string;
  /** Diameter in px; the initials scale with it. */
  size?: number;
  className?: string;
}) {
  return (
    <span
      className={className ? `${styles.avatar} ${className}` : styles.avatar}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.34) }}
      aria-hidden
    >
      {initialsFromName(name)}
    </span>
  );
}
