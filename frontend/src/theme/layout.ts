/**
 * Layout tokens that only JavaScript can consume (FRG-UI-018, FRG-UI-049).
 *
 * The compact crossover is declared HERE and nowhere else: the Calendar's two
 * entry presentations and the shell's sidebar must switch at the same width, and
 * a second literal in a stylesheet could drift from this one. CSS therefore
 * carries no width media query for it — the shell stamps `data-compact` on its
 * root and every compact rule keys off that attribute.
 */

/** Viewport widths below this are compact; at or above it the frame is wide. */
export const COMPACT_CROSSOVER_PX = 900;

/**
 * The one query `useCompactViewport` matches on. It must be EXCLUSIVE of the
 * crossover itself — at 900px the frame is wide — and the shave is sub-pixel
 * rather than a whole pixel so that fractional widths just under the crossover
 * (browser zoom, hidpi scaling) still resolve as compact instead of as the wide
 * frame. Compact is a single boolean derived from this query, so a width that
 * fails it is wide by definition; no width can fall between the two.
 */
export const COMPACT_MEDIA_QUERY = `(max-width: ${COMPACT_CROSSOVER_PX - 0.02}px)`;

/**
 * The WCAG 2.5.8 pointer-target floor (FRG-UI-047), in pixels. The stylesheets
 * spend it as `--layout-touch-target-min`, but a custom property is opaque to
 * anything outside CSS: neither a stylesheet assertion nor a rendered-geometry
 * measurement can read its value, so both would otherwise carry their own
 * literal. This is the one place the number is written.
 */
export const TOUCH_TARGET_MIN_PX = 24;
