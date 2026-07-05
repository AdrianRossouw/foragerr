import { useLayoutEffect, useRef, useState } from 'react';

/**
 * A minimal component that styles itself from the `--color-accent` token
 * (FRG-UI-002). It hardcodes NO brand color — it resolves the token at render and
 * applies it, so overriding `--color-accent` at :root restyles it. Used both in the
 * app shell (brand accent) and as the subject of the accent-override test.
 */
export function AccentSwatch({ label = 'accent' }: { label?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [resolved, setResolved] = useState('');

  useLayoutEffect(() => {
    // Read the token from the document root where the theme (and any override) is
    // declared. This is the standard "read a CSS custom property in JS" pattern.
    const value = getComputedStyle(document.documentElement)
      .getPropertyValue('--color-accent')
      .trim();
    setResolved(value);
  });

  return (
    <span
      ref={ref}
      data-testid="accent-swatch"
      data-accent={resolved}
      style={{ color: 'var(--color-accent)', background: resolved || undefined }}
    >
      {label}
    </span>
  );
}
