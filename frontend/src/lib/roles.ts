/*
 * Creator-role display helpers (FRG-UI-027/028). The wire carries the fixed
 * normalized-role vocabulary as lowercase tokens (writer/artist/…/other); these
 * turn them into human labels for the grid cards, profile, and series strip.
 */

/** Nicer labels for the roles whose token isn't its own display form. */
const ROLE_LABELS: Record<string, string> = {
  cover: 'Cover',
  other: 'Other',
};

/** One role token → a capitalized display label. */
export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role.charAt(0).toUpperCase() + role.slice(1);
}

/** A creator's role set → a comma-joined label line (e.g. "Writer, Artist"). */
export function roleList(roles: readonly string[]): string {
  return roles.map(roleLabel).join(', ');
}
