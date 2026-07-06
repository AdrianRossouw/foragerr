import { useEffect, useState } from 'react';

/**
 * Debounces `value`, updating no more often than every `delayMs` (FRG-UI-005:
 * the Add Series autosuggest debounce). The value passed in on the FIRST
 * render is returned immediately with no artificial delay — only subsequent
 * changes are debounced — so a value seeded on mount (e.g. a prefilled search
 * term carried in from the header quick-search fall-through) is usable at
 * once rather than waiting out a delay against itself.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
