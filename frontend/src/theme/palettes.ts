/*
 * Publisher and format-chip palettes (FRG-UI-002, design decision 1).
 *
 * The owner's design tints cover art placeholders by publisher and colors
 * calendar spines / format chips. These are DATA — looked up per publisher or
 * per collected-edition format at render time — so they live here as exported
 * maps feeding inline styles, NOT as per-publisher CSS classes and NOT as CSS
 * variables in `tokens.css` (which stays the single source for the core
 * surface/accent/status palette). This module is the single source for the
 * publisher/format palette values; components import from here rather than
 * hardcoding a hex.
 */

/** Card/cover background tint shown before ComicVine art loads. */
export const PUBLISHER_TINT: Record<string, string> = {
  Marvel: '#3a2626',
  DC: '#26303c',
  Image: '#2b2b2b',
  'BOOM!': '#3a3124',
  Vertigo: '#2f2638',
  'Dark Horse': '#243030',
  'Cartoon Books': '#26332b',
  IDW: '#2b2b2b',
};

/** Accent used for calendar spines / publisher bars. */
export const PUBLISHER_ACCENT: Record<string, string> = {
  Marvel: '#c0555a',
  DC: '#5a86c0',
  Image: '#9a9a9a',
  'BOOM!': '#c9a24a',
  Vertigo: '#9a6fc0',
  'Dark Horse': '#5aa38f',
  'Cartoon Books': '#6fb87a',
  IDW: '#8a8a8a',
};

/** Fallback tint/accent for an unknown or null publisher. */
export const PUBLISHER_TINT_DEFAULT = '#2b2b2b';
export const PUBLISHER_ACCENT_DEFAULT = '#57b877';

/** A collected-edition format chip's background + text color. */
export interface FormatChipColor {
  bg: string;
  text: string;
}

/**
 * Format-chip palette keyed by the collected-edition book-type family: trade
 * paperbacks read blue, deluxe/hardcover amber, omnibus green. `booktype`
 * values (`tpb`/`gn`/`hc`/`one_shot`) map onto these three families.
 */
export const FORMAT_CHIP: Record<string, FormatChipColor> = {
  tpb: { bg: 'rgba(93, 156, 236, 0.16)', text: '#8ab6f0' },
  gn: { bg: 'rgba(93, 156, 236, 0.16)', text: '#8ab6f0' },
  hc: { bg: 'rgba(198, 132, 66, 0.18)', text: '#d99a5b' },
  omnibus: { bg: 'rgba(87, 184, 119, 0.18)', text: '#7fce9a' },
};

/**
 * Creator role chip palette keyed by the FIXED normalized-role vocabulary
 * (FRG-CRTR-001: writer/artist/penciler/inker/colorist/letterer/cover/editor/
 * other). Like FORMAT_CHIP these are DATA — a per-role tint+text looked up at
 * render time and fed into inline styles — so they live here beside the
 * publisher/format maps, not as CSS tokens. Each role gets a distinct low-alpha
 * wash + a legible text tone so a card's role chips read apart at a glance.
 */
export const ROLE_CHIP: Record<string, FormatChipColor> = {
  writer: { bg: 'rgba(93, 156, 236, 0.16)', text: '#8ab6f0' },
  artist: { bg: 'rgba(155, 111, 192, 0.18)', text: '#b892d8' },
  penciler: { bg: 'rgba(87, 184, 119, 0.16)', text: '#7fce9a' },
  inker: { bg: 'rgba(90, 134, 192, 0.16)', text: '#8fb2d8' },
  colorist: { bg: 'rgba(229, 165, 75, 0.18)', text: '#e0b06a' },
  letterer: { bg: 'rgba(201, 122, 168, 0.18)', text: '#d69ac2' },
  cover: { bg: 'rgba(90, 163, 143, 0.18)', text: '#7fc4b0' },
  editor: { bg: 'rgba(154, 154, 154, 0.16)', text: '#bcbcbc' },
  other: { bg: 'rgba(122, 122, 122, 0.16)', text: '#a4a4a4' },
};

/** Resolve a role's chip colors, falling back to the neutral "other" slot. */
export function roleChip(role: string): FormatChipColor {
  return ROLE_CHIP[role] ?? ROLE_CHIP.other;
}

/** Resolve a publisher's cover tint, falling back to the neutral tint. */
export function publisherTint(publisher: string | null | undefined): string {
  if (!publisher) return PUBLISHER_TINT_DEFAULT;
  return PUBLISHER_TINT[publisher] ?? PUBLISHER_TINT_DEFAULT;
}

/** Resolve a publisher's spine/bar accent, falling back to the brand green. */
export function publisherAccent(publisher: string | null | undefined): string {
  if (!publisher) return PUBLISHER_ACCENT_DEFAULT;
  return PUBLISHER_ACCENT[publisher] ?? PUBLISHER_ACCENT_DEFAULT;
}
