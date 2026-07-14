// FRG-EXT-001 — explicit-action cookie-to-clipboard copy logic.
// Node built-in test runner (node:test / node:assert) — no third-party deps.

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  copyHumbleCookie,
  HUMBLE_COOKIE_NAME,
  HUMBLE_COOKIE_URL,
} from "../src/lib.js";

function fakes({ cookie }) {
  const calls = { cookieQueries: [], clipboardWrites: [] };
  const cookies = async (query) => {
    calls.cookieQueries.push(query);
    return cookie;
  };
  const clipboard = async (text) => {
    calls.clipboardWrites.push(text);
  };
  return { cookies, clipboard, calls };
}

test("FRG-EXT-001: copies the Humble cookie value to the clipboard on demand", async () => {
  const { cookies, clipboard, calls } = fakes({
    cookie: { value: "sess-abc123", expirationDate: 4102444800 },
  });

  const result = await copyHumbleCookie({ cookies, clipboard });

  assert.deepEqual(calls.cookieQueries, [
    { url: HUMBLE_COOKIE_URL, name: HUMBLE_COOKIE_NAME },
  ]);
  assert.deepEqual(calls.clipboardWrites, ["sess-abc123"]);
  assert.equal(result.ok, true);
  assert.equal(result.expiresAt, 4102444800);
});

test("FRG-EXT-001: result never carries the cookie value (expiry hint only)", async () => {
  const { cookies, clipboard } = fakes({
    cookie: { value: "secret-cookie", expirationDate: 4102444800 },
  });

  const result = await copyHumbleCookie({ cookies, clipboard });

  // The returned object must not leak the value anywhere.
  assert.equal(JSON.stringify(result).includes("secret-cookie"), false);
});

test("FRG-EXT-001: no live Humble session — copies nothing, reports no-session", async () => {
  const { cookies, clipboard, calls } = fakes({ cookie: null });

  const result = await copyHumbleCookie({ cookies, clipboard });

  assert.deepEqual(result, { ok: false, reason: "no-session" });
  assert.equal(calls.clipboardWrites.length, 0);
});

test("FRG-EXT-001: empty cookie value is treated as no session", async () => {
  const { cookies, clipboard, calls } = fakes({ cookie: { value: "" } });

  const result = await copyHumbleCookie({ cookies, clipboard });

  assert.equal(result.ok, false);
  assert.equal(calls.clipboardWrites.length, 0);
});

test("FRG-EXT-001: cookie is read fresh each call and never retained by the module", async () => {
  // A second call with a rotated cookie must read again and copy the new value,
  // proving no value is cached between invocations.
  let current = { value: "first" };
  const clipboardWrites = [];
  const cookies = async () => current;
  const clipboard = async (t) => {
    clipboardWrites.push(t);
  };

  await copyHumbleCookie({ cookies, clipboard });
  current = { value: "second" };
  await copyHumbleCookie({ cookies, clipboard });

  assert.deepEqual(clipboardWrites, ["first", "second"]);
});

test("FRG-EXT-001: missing expirationDate yields a null hint, still ok", async () => {
  const { cookies, clipboard } = fakes({ cookie: { value: "sess-x" } });

  const result = await copyHumbleCookie({ cookies, clipboard });

  assert.deepEqual(result, { ok: true, expiresAt: null });
});
