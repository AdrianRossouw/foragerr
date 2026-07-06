import styles from './Poster.module.css';

/*
 * Shared poster frame (FRG-UI-003/004/005): a 2:3 frame with a fallback initial
 * behind an optional cover image. Adopts the strictest of the former three
 * inlined variants — the image is rendered ONLY when a src is present (so a
 * missing cover shows the fallback rather than a broken image). Callers pass
 * their context-specific frame/fallback classes so sizing stays per-screen.
 */
export interface PosterProps {
  /** Fallback initial shown behind (or instead of) the cover image. */
  initial: string;
  /** Cover image src; when null/undefined only the fallback renders. */
  src?: string | null;
  /** Image alt text (ignored when there is no src). */
  alt: string;
  /** Context-specific frame styling (size, radius, background, shadow). */
  frameClassName?: string;
  /** Context-specific fallback styling (font-size). */
  fallbackClassName?: string;
  /** Lazy-load the cover image (grids/lists). */
  lazy?: boolean;
}

export function Poster({
  initial,
  src,
  alt,
  frameClassName,
  fallbackClassName,
  lazy = false,
}: PosterProps) {
  return (
    <span
      className={frameClassName ? `${styles.frame} ${frameClassName}` : styles.frame}
    >
      <span
        className={
          fallbackClassName
            ? `${styles.fallback} ${fallbackClassName}`
            : styles.fallback
        }
        aria-hidden
      >
        {initial}
      </span>
      {src != null && (
        <img
          className={styles.poster}
          src={src}
          alt={alt}
          {...(lazy ? { loading: 'lazy' as const } : {})}
        />
      )}
    </span>
  );
}
