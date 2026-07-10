import type { CSSProperties, ReactNode } from 'react';
import styles from './Chip.module.css';

/**
 * Shared chip/pill (FRG-UI-003, design decision 2). A small rounded label used
 * for publisher / volume / `N vols` tags and status pills across the library
 * views. Tone maps to the semantic token palette; `neutral` is the default
 * dark chip. All color comes from tokens — callers never pass a hex.
 */
export type ChipTone = 'neutral' | 'success' | 'warning' | 'info' | 'muted';

export function Chip({
  children,
  tone = 'neutral',
  className,
  title,
  style,
  testId,
}: {
  children: ReactNode;
  tone?: ChipTone;
  className?: string;
  title?: string;
  style?: CSSProperties;
  testId?: string;
}) {
  return (
    <span
      className={`${styles.chip} ${styles[tone]}${className ? ` ${className}` : ''}`}
      title={title}
      style={style}
      data-testid={testId}
    >
      {children}
    </span>
  );
}
