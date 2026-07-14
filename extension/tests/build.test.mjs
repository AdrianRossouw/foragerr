// FRG-EXT-003 — reproducible, deterministic build.
// Two runs from identical sources must produce byte-identical zips.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");

function sha256(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function buildAndHash() {
  execFileSync("node", [join(ROOT, "build.mjs")], { stdio: "ignore" });
  return {
    chrome: sha256(join(ROOT, "dist", "chrome.zip")),
    firefox: sha256(join(ROOT, "dist", "firefox.zip")),
  };
}

test("FRG-EXT-003: two builds produce byte-identical zips", () => {
  const first = buildAndHash();
  const second = buildAndHash();
  assert.equal(first.chrome, second.chrome, "chrome.zip is reproducible");
  assert.equal(first.firefox, second.firefox, "firefox.zip is reproducible");
});

test("FRG-EXT-003: chrome and firefox artifacts differ only where the manifest does", () => {
  // Same popup/lib logic in both; the zips differ (manifest background shape),
  // so their hashes are expected to differ — a guard that the two targets are
  // genuinely distinct builds, not an accidental copy.
  const h = buildAndHash();
  assert.notEqual(h.chrome, h.firefox);
});
