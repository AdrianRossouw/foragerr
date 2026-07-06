import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useDebouncedValue } from './useDebouncedValue';

/**
 * FRG-UI-005 — the Add Series autosuggest's debounce primitive: fires only
 * after the delay elapses, and rapid intermediate changes never commit —
 * only the final value does, so a burst of keystrokes collapses to one
 * eventual suggest request rather than one per keystroke.
 */
describe('FRG-UI-005: useDebouncedValue', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('FRG-UI-005 — returns the seeded value immediately on mount, before any delay elapses', () => {
    const { result } = renderHook(() => useDebouncedValue('saga', 250));
    expect(result.current).toBe('saga');
  });

  it('FRG-UI-005 — only commits after the delay, and rapid intermediate changes never commit (debounced, not per-keystroke)', () => {
    const { result, rerender } = renderHook(
      ({ value }) => useDebouncedValue(value, 250),
      { initialProps: { value: 's' } },
    );

    rerender({ value: 'sa' });
    act(() => vi.advanceTimersByTime(100));
    rerender({ value: 'sag' });
    act(() => vi.advanceTimersByTime(100));
    rerender({ value: 'saga' });
    // Neither intermediate value ('sa'/'sag') ever committed.
    expect(result.current).toBe('s');

    act(() => vi.advanceTimersByTime(250));
    expect(result.current).toBe('saga');
  });
});
