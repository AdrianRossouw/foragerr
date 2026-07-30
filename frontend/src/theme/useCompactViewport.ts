import { useEffect, useState } from 'react';
import { COMPACT_MEDIA_QUERY } from './layout';

/**
 * True while the viewport is below the single compact crossover (FRG-UI-018,
 * FRG-UI-049). Both the Calendar's entry presentation and the shell's sidebar
 * read this one hook, so they can never disagree about which mode is active.
 *
 * A control that must be ABSENT above the crossover (the shell's nav toggle)
 * cannot be expressed as a CSS media query — hiding it would leave it in the
 * accessibility tree and in keyboard order — so the crossover is evaluated in
 * JS and the presentations differ by DOM, not by visibility.
 *
 * `matchMedia` is guarded because a test host may not implement it: without the
 * guard those cases throw instead of rendering the wide frame. The app ships as
 * a browser-only bundle, so `window` itself is always present.
 */
function matchesCompact(): boolean {
  if (typeof window.matchMedia !== 'function') return false;
  return window.matchMedia(COMPACT_MEDIA_QUERY).matches;
}

export function useCompactViewport(): boolean {
  const [compact, setCompact] = useState(matchesCompact);

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const list = window.matchMedia(COMPACT_MEDIA_QUERY);
    const sync = () => setCompact(list.matches);
    // Re-read on mount: the query may already have flipped between the state
    // initializer and this effect (a resize during hydration).
    sync();
    list.addEventListener('change', sync);
    return () => list.removeEventListener('change', sync);
  }, []);

  return compact;
}
