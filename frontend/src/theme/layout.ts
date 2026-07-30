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
 * `max-width` is exclusive of the crossover itself, and the 0.02px shave keeps
 * fractional viewport widths (browser zoom, hidpi scaling) from falling into a
 * band that matches neither presentation.
 */
export const COMPACT_MEDIA_QUERY = `(max-width: ${COMPACT_CROSSOVER_PX - 0.02}px)`;
