#!/usr/bin/env bash
#
# refresh-readme-shots.sh (FRG-PROC-017) — one command to regenerate the README
# tour's screenshots from the running app against the public-domain demo library.
#
# Pipeline: run -> populate -> capture -> optimize -> verify.
#   1. run      start the backend serving the built SPA against /comics
#   2. populate register /comics and library-import it when the library is empty
#   3. capture  drive the app with e2e/scripts/capture-readme-shots.ts
#   4. optimize quantize every PNG down to the in-repo asset budget (<=300 KB)
#   5. verify   fail (non-zero) if any expected shot is missing or over budget
#
# A change that alters the shipped UI's appearance re-runs this and commits the
# refreshed docs/readme-assets/*.png so the public labelling never lags the
# shipped design. Secrets: COMICVINE_API_KEY is read from .env and exported as
# FORAGERR_COMICVINE_API_KEY WITHOUT ever being printed.
#
# Usage:  tools/refresh-readme-shots.sh          (from the repo root)
# Env overrides: FORAGERR_PORT (8790), COMICS_DIR (/comics), SHOT_BUDGET (300000)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${FORAGERR_PORT:-8790}"
BASE_URL="http://127.0.0.1:${PORT}"
COMICS_DIR="${COMICS_DIR:-/comics}"
BUDGET="${SHOT_BUDGET:-300000}"
ASSET_DIR="${REPO}/docs/readme-assets"
CAPTURE_TS="${REPO}/e2e/scripts/capture-readme-shots.ts"
CONFIG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/foragerr-shots.XXXXXX")"
BACKEND_PID=""

log() { printf '[refresh-readme-shots] %s\n' "$*" >&2; }
fail() { log "ERROR: $*"; exit 1; }

cleanup() {
  [ -n "${BACKEND_PID}" ] && kill "${BACKEND_PID}" >/dev/null 2>&1 || true
  rm -rf "${CONFIG_DIR}" || true
}
trap cleanup EXIT

# The expected shot set is derived from the capture script itself, so this tool
# and the capture script can never disagree about which screens the README needs.
mapfile -t SHOTS < <(grep -oE "id: '[a-z0-9-]+'" "${CAPTURE_TS}" | sed "s/id: '//;s/'//")
[ "${#SHOTS[@]}" -ge 5 ] || fail "could not parse the shot set from ${CAPTURE_TS}"
log "shot set: ${SHOTS[*]}"

# --- Build the SPA (the backend serves it as static files) -------------------
log "building frontend…"
( cd "${REPO}/frontend" && npm run build >/dev/null ) || fail "frontend build failed"

# --- Secrets: load the ComicVine key without echoing it ----------------------
if [ -f "${REPO}/.env" ]; then
  CVKEY="$(grep -E '^COMICVINE_API_KEY=' "${REPO}/.env" | head -1 | cut -d= -f2- || true)"
  [ -n "${CVKEY:-}" ] && export FORAGERR_COMICVINE_API_KEY="${CVKEY}"
  unset CVKEY
fi

# --- Start the backend against the demo library ------------------------------
export FORAGERR_CONFIG_DIR="${CONFIG_DIR}"
export FORAGERR_HOST=127.0.0.1
export FORAGERR_PORT="${PORT}"
export FORAGERR_LOG_LEVEL=WARNING
export FORAGERR_LIBRARY_IMPORT_MODE=move
export FORAGERR_STATIC_DIR="${REPO}/frontend/dist"

log "starting backend on ${BASE_URL}…"
( cd "${REPO}/backend" && exec uv run foragerr ) &
BACKEND_PID=$!

for _ in $(seq 1 60); do
  if curl -fsS "${BASE_URL}/health" >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS "${BASE_URL}/health" >/dev/null 2>&1 || fail "backend did not become healthy"

# --- Populate the library if empty (register /comics, then library-import) ---
series_count() {
  curl -fsS "${BASE_URL}/api/v1/series?page=1&pageSize=1" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("totalRecords",0))'
}

if [ "$(series_count)" -eq 0 ]; then
  log "library empty — importing ${COMICS_DIR}"
  [ -d "${COMICS_DIR}" ] || fail "demo library ${COMICS_DIR} does not exist"

  ROOT_ID="$(curl -fsS -X POST "${BASE_URL}/api/v1/rootfolder" \
    -H 'content-type: application/json' -d "{\"path\":\"${COMICS_DIR}\"}" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"

  curl -fsS -X POST "${BASE_URL}/api/v1/library-import/scan" \
    -H 'content-type: application/json' -d "{\"rootFolderId\":${ROOT_ID}}" >/dev/null

  # Wait for the scan to stage groups with a ComicVine proposal.
  GROUP_IDS=""
  for _ in $(seq 1 60); do
    GROUP_IDS="$(curl -fsS "${BASE_URL}/api/v1/library-import?rootFolderId=${ROOT_ID}" \
      | python3 -c 'import json,sys
d=json.load(sys.stdin)
ids=[g["id"] for g in d.get("records",[]) if g.get("proposedCvVolumeId")]
print(",".join(str(i) for i in ids))')"
    [ -n "${GROUP_IDS}" ] && break
    sleep 2
  done
  [ -n "${GROUP_IDS}" ] || fail "no importable library-import groups were staged"

  IDS_JSON="[$(echo "${GROUP_IDS}" | sed 's/,/, /g')]"
  curl -fsS -X POST "${BASE_URL}/api/v1/library-import/execute" \
    -H 'content-type: application/json' \
    -d "{\"groupIds\":${IDS_JSON},\"addOptions\":{\"monitorStrategy\":\"all\",\"monitorNewItems\":\"all\",\"formatProfileId\":null,\"searchOnAdd\":false}}" \
    >/dev/null || fail "library-import execute failed"

  # Give the chained refresh/scan a moment to land covers + issues.
  for _ in $(seq 1 60); do
    [ "$(series_count)" -gt 0 ] && break
    sleep 2
  done
  [ "$(series_count)" -gt 0 ] || fail "import completed but the library is still empty"
fi
log "library has $(series_count) series"

# --- Capture -----------------------------------------------------------------
# This sandbox's node lacks TypeScript type-stripping, so transpile then run
# (the fallback documented in capture-readme-shots.ts's header).
log "capturing screenshots…"
CAP_OUT="$(mktemp -d "${TMPDIR:-/tmp}/foragerr-capture.XXXXXX")"
( cd "${REPO}/e2e" \
  && node_modules/.bin/tsc --module nodenext --target es2022 --moduleResolution nodenext \
       --outDir "${CAP_OUT}" scripts/capture-readme-shots.ts \
  && BASE_URL="${BASE_URL}" OUT_DIR="${ASSET_DIR}" node "${CAP_OUT}/capture-readme-shots.js" ) \
  || fail "capture script failed"
rm -rf "${CAP_OUT}"

# --- Optimize: quantize each PNG down to the budget --------------------------
log "optimizing PNGs to <=${BUDGET} bytes…"
python3 - "${ASSET_DIR}" "${BUDGET}" "${SHOTS[@]}" <<'PY'
import sys
from pathlib import Path
from PIL import Image

asset_dir, budget = Path(sys.argv[1]), int(sys.argv[2])
shots = sys.argv[3:]
for shot in shots:
    p = asset_dir / f"{shot}.png"
    if not p.exists():
        continue
    if p.stat().st_size <= budget:
        continue
    img = Image.open(p).convert("RGB")
    for colors in (256, 192, 128, 96, 64):
        q = img.quantize(colors=colors, method=Image.MEDIANCUT)
        q.save(p, format="PNG", optimize=True)
        if p.stat().st_size <= budget:
            break
    print(f"optimized {p.name} -> {p.stat().st_size} bytes", file=sys.stderr)
PY

# --- Verify: every expected shot exists and is within budget -----------------
missing=0
for shot in "${SHOTS[@]}"; do
  f="${ASSET_DIR}/${shot}.png"
  if [ ! -f "${f}" ]; then log "MISSING ${f}"; missing=1; continue; fi
  size="$(wc -c < "${f}")"
  if [ "${size}" -gt "${BUDGET}" ]; then log "OVER BUDGET ${f} (${size} > ${BUDGET})"; missing=1; fi
done
[ "${missing}" -eq 0 ] || fail "one or more README shots are missing or over budget"

log "refreshed ${#SHOTS[@]} README screenshots under ${ASSET_DIR}"
