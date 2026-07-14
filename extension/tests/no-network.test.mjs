// FRG-EXT-002 — the extension has no network capability.
//
// IMPORTANT framing: a narrow `host_permissions` does NOT stop a WebExtension
// from making write-only egress requests (fetch no-cors, sendBeacon, an Image
// src, a WebSocket, RTCPeerConnection) to any origin, and the default MV3 CSP
// does not set connect-src. So the no-network property is enforced by the
// shipped source containing no egress code (verified here) + MV3's no-remote-
// code guarantee + the minimal manifest — NOT by the sandbox. This scan is a
// tripwire against an accidental future edit, not a proof: a determined author
// can obfuscate egress (bracket/aliased identifiers) past any denylist. Real
// assurance comes from code review of a small, reproducible bundle.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, "..", "src");

// Egress vectors (plain identifier forms). Not exhaustive by design — see the
// header note; the manifest negatives (no nativeMessaging/optional perms/CSP)
// and MV3 no-remote-code cover the rest.
const FORBIDDEN = [
  /\bfetch\s*\(/,
  /\bXMLHttpRequest\b/,
  /\bWebSocket\b/,
  /\bsendBeacon\b/,
  /\bEventSource\b/,
  /\bRTCPeerConnection\b/,
  /new\s+Image\b/,
  /\.src\s*=/, // no img/script src assignment
  /\bimport\s*\(/, // no dynamic import of remote/other code
  /\beval\s*\(/,
  /new\s+Function\b/,
  /url\(\s*['"]?https?:/i, // no CSS url() beacon in inline styles
];

test("FRG-EXT-002: no network/egress primitives in the extension source", () => {
  // Scan every shipped source file, not only .js/.html.
  const files = readdirSync(SRC).filter((f) =>
    /\.(m?js|html|css)$/.test(f),
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
