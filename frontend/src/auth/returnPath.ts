/**
 * Shared safe-return-path helper for the login redirect flow (m8-auth-core,
 * FRG-AUTH-002). The `return` query param is attacker-controllable via a
 * crafted `/login?return=` link, so it must be validated before it reaches
 * `navigate()`.
 *
 * A substring check (`startsWith('/') && !startsWith('//')`) is NOT enough:
 * the WHATWG URL parser normalizes backslashes to slashes and strips embedded
 * tab/newline/CR for special schemes, so values like `/\evil.com` or
 * `/<TAB>/evil.com` pass a substring guard yet resolve cross-origin. React
 * Router's `navigate(..., { replace: true })` then calls
 * `history.replaceState`, which throws an uncaught `DOMException` when the
 * resolved URL is cross-origin — crashing the SPA to a blank page. So we
 * resolve the candidate against the real origin and accept it only when the
 * resolved origin matches AND it stays a path (no host, no scheme).
 */
export function safeReturnPath(raw: string | null | undefined): string {
  if (!raw) return '/';
  try {
    const resolved = new URL(raw, window.location.origin);
    if (resolved.origin !== window.location.origin) return '/';
    // Reject anything that parsed to a different host slot even at same origin
    // edge cases; keep only the path + query + hash we resolved to.
    const path = `${resolved.pathname}${resolved.search}${resolved.hash}`;
    return path.startsWith('/') ? path : '/';
  } catch {
    return '/';
  }
}
