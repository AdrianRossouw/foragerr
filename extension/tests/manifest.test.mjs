// FRG-EXT-002 — least-privilege, no-network permission surface.
// Asserts the built manifests declare exactly the intended narrow surface.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");

// Build fresh into an isolated dir so this test never races the build test's
// output under parallel `node --test` (both invoke build.mjs, which rm's DIST).
const OUT = "dist-test-manifest";
execFileSync("node", [join(ROOT, "build.mjs")], {
  stdio: "ignore",
  env: { ...process.env, EXT_DIST_DIR: OUT },
});

function manifest(target) {
  return JSON.parse(
    readFileSync(join(ROOT, OUT, target, "manifest.json"), "utf8"),
  );
}

for (const target of ["chrome", "firefox"]) {
  test(`FRG-EXT-002: ${target} manifest declares only cookies + clipboardWrite and the single Humble host`, () => {
    const m = manifest(target);
    assert.equal(m.manifest_version, 3);
    assert.deepEqual([...m.permissions].sort(), ["clipboardWrite", "cookies"]);
    assert.deepEqual(m.host_permissions, ["https://www.humblebundle.com/*"]);
  });

  test(`FRG-EXT-002: ${target} manifest declares no broad or code-exposing surface`, () => {
    const m = manifest(target);
    for (const forbidden of [
      "content_scripts",
      "externally_connectable",
      "web_accessible_resources",
      "devtools_page",
      "chrome_url_overrides",
      // Egress / broad-reach keys a host permission would NOT prevent — the
      // no-network property rests on these being absent, not on host scope.
      "nativeMessaging",
      "content_security_policy",
      "optional_permissions",
      "optional_host_permissions",
      "declarative_net_request",
    ]) {
      assert.equal(m[forbidden], undefined, `must not declare ${forbidden}`);
    }
    // No extra host permission beyond Humble, and no <all_urls>/tabs/storage.
    for (const perm of ["tabs", "storage", "webRequest", "<all_urls>"]) {
      assert.equal(
        m.permissions.includes(perm),
        false,
        `must not request ${perm}`,
      );
    }
    assert.equal(
      m.host_permissions.some((h) => h.includes("*://") || h === "<all_urls>"),
      false,
      "no wildcard host",
    );
  });
}

test("FRG-EXT-002: chrome uses a service worker, firefox uses background scripts", () => {
  assert.equal(manifest("chrome").background.service_worker, "background.js");
  assert.deepEqual(manifest("firefox").background.scripts, ["background.js"]);
  assert.ok(manifest("firefox").browser_specific_settings.gecko.id);
});
