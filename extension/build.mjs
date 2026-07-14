#!/usr/bin/env node
// Deterministic, dependency-free build for the foragerr Humble cookie helper.
//
// Emits dist/chrome/ and dist/firefox/ from the shared src/ tree plus a
// per-browser manifest, then writes a byte-stable .zip for each (FRG-EXT-003).
// Uses only the Node standard library — no third-party build or runtime deps,
// so nothing lands in the SOUP register. The zip is STORED (no compression)
// with fixed timestamps and sorted entries, so two runs from identical sources
// produce byte-identical archives an operator can verify against.

import { readFileSync, writeFileSync, mkdirSync, rmSync, cpSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, "src");
// Output dir is overridable so parallel test runs build into isolated dirs
// instead of racing on a shared ./dist (they otherwise rm each other's output).
const DIST = process.env.EXT_DIST_DIR
  ? join(HERE, process.env.EXT_DIST_DIR)
  : join(HERE, "dist");

const base = JSON.parse(readFileSync(join(HERE, "manifest.base.json"), "utf8"));

// The only per-browser difference: the MV3 background slot. Chrome uses a
// service worker; Firefox MV3 uses background scripts + an add-on id.
const TARGETS = {
  chrome: {
    background: { service_worker: "background.js", type: "module" },
  },
  firefox: {
    background: { scripts: ["background.js"] },
    browser_specific_settings: {
      gecko: { id: "humble-cookie@foragerr.local" },
    },
  },
};

// Files copied verbatim into every build, in a fixed order.
const SHARED_FILES = ["popup.html", "popup.js", "lib.js", "background.js"];

// ---- minimal deterministic ZIP (STORED / method 0) ------------------------

function crc32(buf) {
  let crc = 0xffffffff;
  for (let i = 0; i < buf.length; i++) {
    crc ^= buf[i];
    for (let b = 0; b < 8; b++) {
      crc = crc & 1 ? (crc >>> 1) ^ 0xedb88320 : crc >>> 1;
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

// Fixed DOS date/time: 1980-01-01 00:00:00 — removes wall-clock nondeterminism.
const DOS_TIME = 0x0000;
const DOS_DATE = 0x0021;

function zipStored(entries) {
  // entries: [{name, data:Buffer}] — caller passes them already sorted.
  const locals = [];
  const centrals = [];
  let offset = 0;

  for (const { name, data } of entries) {
    const nameBuf = Buffer.from(name, "utf8");
    const crc = crc32(data);

    const local = Buffer.alloc(30 + nameBuf.length);
    local.writeUInt32LE(0x04034b50, 0); // local file header signature
    local.writeUInt16LE(20, 4); // version needed
    local.writeUInt16LE(0, 6); // flags
    local.writeUInt16LE(0, 8); // method: stored
    local.writeUInt16LE(DOS_TIME, 10);
    local.writeUInt16LE(DOS_DATE, 12);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(data.length, 18); // compressed size
    local.writeUInt32LE(data.length, 22); // uncompressed size
    local.writeUInt16LE(nameBuf.length, 26);
    local.writeUInt16LE(0, 28); // extra length
    nameBuf.copy(local, 30);
    locals.push(local, data);

    const central = Buffer.alloc(46 + nameBuf.length);
    central.writeUInt32LE(0x02014b50, 0); // central dir header signature
    central.writeUInt16LE(20, 4); // version made by
    central.writeUInt16LE(20, 6); // version needed
    central.writeUInt16LE(0, 8); // flags
    central.writeUInt16LE(0, 10); // method
    central.writeUInt16LE(DOS_TIME, 12);
    central.writeUInt16LE(DOS_DATE, 14);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(data.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(nameBuf.length, 28);
    central.writeUInt16LE(0, 30); // extra length
    central.writeUInt16LE(0, 32); // comment length
    central.writeUInt16LE(0, 34); // disk number start
    central.writeUInt16LE(0, 36); // internal attrs
    central.writeUInt32LE(0, 38); // external attrs
    central.writeUInt32LE(offset, 42); // local header offset
    nameBuf.copy(central, 46);
    centrals.push(central);

    offset += local.length + data.length;
  }

  const centralDir = Buffer.concat(centrals);
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0); // EOCD signature
  eocd.writeUInt16LE(0, 4); // disk number
  eocd.writeUInt16LE(0, 6); // disk with central dir
  eocd.writeUInt16LE(entries.length, 8); // entries on this disk
  eocd.writeUInt16LE(entries.length, 10); // total entries
  eocd.writeUInt32LE(centralDir.length, 12); // central dir size
  eocd.writeUInt32LE(offset, 16); // central dir offset
  eocd.writeUInt16LE(0, 20); // comment length

  return Buffer.concat([...locals, centralDir, eocd]);
}

// ---- build -----------------------------------------------------------------

function buildTarget(name) {
  const outDir = join(DIST, name);
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });

  // Object-spread key order is deterministic (base keys, then the per-target
  // additions), so a plain stringify is already reproducible — and, unlike an
  // array replacer, it does not filter nested manifest keys.
  const manifest = { ...base, ...TARGETS[name] };
  const manifestJson = JSON.stringify(manifest, null, 2);

  // Collect { name -> data } then sort by name for a deterministic archive.
  const files = new Map();
  files.set("manifest.json", Buffer.from(manifestJson + "\n", "utf8"));
  for (const f of SHARED_FILES) {
    files.set(f, readFileSync(join(SRC, f)));
  }

  // Write the unpacked dir (for Chrome developer-mode load).
  for (const [fname, data] of files) {
    writeFileSync(join(outDir, fname), data);
  }

  // Write the deterministic zip alongside it.
  const entries = [...files.keys()]
    .sort()
    .map((n) => ({ name: n, data: files.get(n) }));
  const zip = zipStored(entries);
  writeFileSync(join(DIST, `${name}.zip`), zip);

  return zip.length;
}

function main() {
  rmSync(DIST, { recursive: true, force: true });
  mkdirSync(DIST, { recursive: true });
  for (const name of Object.keys(TARGETS)) {
    const size = buildTarget(name);
    process.stdout.write(`built ${name}: dist/${name}/ + dist/${name}.zip (${size} bytes)\n`);
  }
}

main();

// Exported for the deterministic-build and manifest tests.
export { zipStored, crc32, TARGETS, base, SHARED_FILES, buildTarget };
