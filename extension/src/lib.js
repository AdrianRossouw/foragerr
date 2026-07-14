// Pure, browser-agnostic copy logic for the foragerr Humble cookie helper.
//
// This module contains NO direct access to the WebExtension APIs or the DOM:
// the caller injects a `cookies` reader and a `clipboard` writer, so the logic
// is unit-testable under Node with plain fakes and carries no network code.
// (FRG-EXT-001: read on explicit action, copy to clipboard, never retain,
//  never transmit. FRG-EXT-002: nothing here reaches the network.)

export const HUMBLE_COOKIE_URL = "https://www.humblebundle.com/";
export const HUMBLE_COOKIE_NAME = "_simpleauth_sess";

/**
 * Read the Humble session cookie and copy it to the clipboard.
 *
 * @param {object} deps
 * @param {(query: {url: string, name: string}) => Promise<{value: string, expirationDate?: number} | null>} deps.cookies
 *        Reader returning the cookie object or null when absent.
 * @param {(text: string) => Promise<void>} deps.clipboard  Clipboard writer.
 * @returns {Promise<{ok: true, expiresAt: number | null} | {ok: false, reason: "no-session"}>}
 *          On success reports only the expiry hint — never the cookie value.
 */
export async function copyHumbleCookie({ cookies, clipboard }) {
  const cookie = await cookies({
    url: HUMBLE_COOKIE_URL,
    name: HUMBLE_COOKIE_NAME,
  });

  // Not logged in to Humble (or the cookie was cleared): copy nothing.
  if (!cookie || typeof cookie.value !== "string" || cookie.value === "") {
    return { ok: false, reason: "no-session" };
  }

  // Copy the value, then let it fall out of scope — we never store it.
  await clipboard(cookie.value);

  const expiresAt =
    typeof cookie.expirationDate === "number" ? cookie.expirationDate : null;
  return { ok: true, expiresAt };
}
