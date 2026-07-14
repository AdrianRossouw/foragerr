// FRG-EXT-002 — the extension has no network capability.
// Source-scan invariant: no fetch / XMLHttpRequest / WebSocket / sendBeacon /
// EventSource anywhere in the shipped extension source. The cookie can leave
// only via the clipboard the operator controls.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, "..", "src");

// Patterns that would indicate a network egress path.
const FORBIDDEN = [
  /\bfetch\s*\(/,
  /\bXMLHttpRequest\b/,
  /\bWebSocket\b/,
  /\bnavigator\.sendBeacon\b/,
  /\bEventSource\b/,
  /\bimport\s*\(/, // no dynamic import of remote/other code
];

test("FRG-EXT-002: no network primitives in the extension source", () => {
  const files = readdirSync(SRC).filter(
    (f) => f.endsWith(".js") || f.endsWith(".html"),
  );
  assert.ok(files.length >= 4, "expected the shared source files present");

  for (const file of files) {
    const text = readFileSync(join(SRC, file), "utf8");
    for (const pattern of FORBIDDEN) {
      assert.equal(
        pattern.test(text),
        false,
        `${file} must not contain ${pattern}`,
      );
    }
  }
});
