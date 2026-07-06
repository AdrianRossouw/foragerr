import type { NamingTokens } from '../../../api/types';

/*
 * Present the shared token vocabulary (FRG-UI-012). The token names come SOLELY
 * from the backend alias table (GET /config/naming/tokens) — this module only
 * reshapes that one definition into per-field cheatsheet rows for the `?`
 * help popover, so there is no hand-maintained duplicate token list.
 */

export interface TokenGroup {
  /** Canonical field key (e.g. "series_title"). */
  field: string;
  /** A display token to show/insert, e.g. "{Series Title}". */
  display: string;
  /** Every accepted spelling of this token, longest first. */
  aliases: string[];
}

function titleCase(name: string): string {
  return name
    .split(' ')
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(' ');
}

/**
 * Group the alias table by canonical field, preserving the table's insertion
 * order for stable rendering. The display token is the longest alias
 * title-cased (e.g. "issue number" -> "{Issue Number}"), which reads best in the
 * cheatsheet; the renderer canonicalizes case/spacing so any listed spelling
 * resolves identically.
 */
export function tokenGroups(tokens: NamingTokens | undefined): TokenGroup[] {
  if (!tokens) return [];
  const byField = new Map<string, string[]>();
  for (const [alias, field] of Object.entries(tokens.aliases)) {
    const list = byField.get(field) ?? [];
    list.push(alias);
    byField.set(field, list);
  }
  return [...byField.entries()].map(([field, aliases]) => {
    const sorted = [...aliases].sort((a, b) => b.length - a.length);
    return { field, display: `{${titleCase(sorted[0])}}`, aliases: sorted };
  });
}
