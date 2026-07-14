// Popup entry point. Wires the single "Copy" button to the pure copy logic,
// binding the injected dependencies to the live WebExtension cookie API and
// the clipboard. All work happens inside the click handler's user gesture
// (FRG-EXT-001) — nothing runs on load beyond wiring the listener.

import { copyHumbleCookie } from "./lib.js";

// Chrome exposes `chrome`; Firefox exposes `browser` (promise-based). The
// cookies.get shape is identical; wrap chrome's callback form in a promise.
const api = typeof browser !== "undefined" ? browser : chrome;

function getCookie(query) {
  const maybe = api.cookies.get(query);
  // Firefox returns a promise; Chrome MV3 also returns a promise, but guard
  // the legacy callback shape just in case.
  if (maybe && typeof maybe.then === "function") return maybe;
  return new Promise((resolve) => api.cookies.get(query, resolve));
}

function writeClipboard(text) {
  return navigator.clipboard.writeText(text);
}

function formatExpiry(expiresAt) {
  if (!expiresAt) return "";
  const days = Math.round((expiresAt * 1000 - Date.now()) / 86_400_000);
  if (days <= 0) return " Session looks expired — log in to Humble again.";
  return ` Session valid for about ${days} more day${days === 1 ? "" : "s"}.`;
}

function setStatus(el, message, kind) {
  el.textContent = message;
  el.dataset.kind = kind;
}

document.addEventListener("DOMContentLoaded", () => {
  const button = document.getElementById("copy");
  const status = document.getElementById("status");

  button.addEventListener("click", async () => {
    button.disabled = true;
    setStatus(status, "Copying…", "pending");
    try {
      const result = await copyHumbleCookie({
        cookies: getCookie,
        clipboard: writeClipboard,
      });
      if (result.ok) {
        setStatus(
          status,
          "Copied. Paste it into foragerr's Sources card." +
            formatExpiry(result.expiresAt),
          "ok",
        );
      } else {
        setStatus(
          status,
          "No Humble session found — log in to Humble first, then try again.",
          "warn",
        );
      }
    } catch (err) {
      setStatus(status, `Couldn't copy: ${err.message}`, "error");
    } finally {
      button.disabled = false;
    }
  });
});
