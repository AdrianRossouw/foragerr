import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { AccentSwatch } from '../components/AccentSwatch';

/**
 * FRG-UI-002 — Scenario: Changing the accent token restyles all screens.
 * A component that styles from `--color-accent` must reflect the overridden value
 * and must NOT hardcode a brand color literal.
 */
afterEach(() => {
  cleanup();
  document.documentElement.style.removeProperty('--color-accent');
});

function accentOf(): string {
  return screen.getByTestId('accent-swatch').getAttribute('data-accent') ?? '';
}

describe('FRG-UI-002: overriding --color-accent restyles accent components', () => {
  it('FRG-UI-002 — component reflects the accent value overridden at :root', () => {
    document.documentElement.style.setProperty('--color-accent', 'rgb(1, 2, 3)');
    render(<AccentSwatch />);
    expect(accentOf()).toBe('rgb(1, 2, 3)');
  });

  it('FRG-UI-002 — changing the override changes what the component renders', () => {
    document.documentElement.style.setProperty('--color-accent', 'rgb(1, 2, 3)');
    const { unmount } = render(<AccentSwatch />);
    expect(accentOf()).toBe('rgb(1, 2, 3)');
    unmount();

    document.documentElement.style.setProperty('--color-accent', 'rgb(9, 8, 7)');
    render(<AccentSwatch />);
    expect(accentOf()).toBe('rgb(9, 8, 7)');
  });

  it('FRG-UI-002 — accent component reads the token, not a hardcoded brand literal', () => {
    document.documentElement.style.setProperty('--color-accent', 'rgb(1, 2, 3)');
    render(<AccentSwatch />);
    // The element styles its color from the token expression itself.
    const el = screen.getByTestId('accent-swatch');
    expect(el.style.color).toBe('var(--color-accent)');
  });
});
