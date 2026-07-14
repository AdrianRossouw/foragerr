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
# Env overrides: FORAGERR_PORT (8791), COMICS_DIR (/comics/_pd-demo — a PD-only
#   library kept separate from any working/testing root), SHOT_BUDGET (300000)
#
# The default port is deliberately NOT 8790: that is the operator's long-lived
# demo instance, which accumulates real browsing state and non-public-domain
# content — screenshots for public labelling must only ever come from the
# fresh, PD-seeded instance this tool starts itself (owner instruction
# 2026-07-11). The stale-port guard below protects against accidents either
# way; FORAGERR_REFRESH_REUSE=1 remains for hermetic environments only.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${FORAGERR_PORT:-8791}"
BASE_URL="http://127.0.0.1:${PORT}"
# A PD-ONLY library, deliberately segregated from the operator's working/testing
# root: README shots are public and must show public-domain content only, and
# the completeness guard below refuses to ship a tour if any folder fails to
# match ComicVine — so testing content (copyrighted titles, half-imported
# folders) sharing the root would both poison the shots and abort the run.
COMICS_DIR="${COMICS_DIR:-/comics/_pd-demo}"
BUDGET="${SHOT_BUDGET:-300000}"
ASSET_DIR="${REPO}/docs/readme-assets"
CAPTURE_TS="${REPO}/e2e/scripts/capture-readme-shots.ts"
CONFIG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/foragerr-shots.XXXXXX")"
BACKEND_PID=""
JAR="${CONFIG_DIR}/cookies.txt"

# Mandatory login (M8 auth): the backend fail-fasts at boot without an operator
# account, and every /api/v1 call is behind the default-deny perimeter, so the
# capture instance must be seeded with a throwaway admin and the populate calls
# + capture browser must authenticate. Hermetic values for a temp instance that
# holds no real secrets; both are overridable (e.g. the FORAGERR_REFRESH_REUSE
# path against an operator instance).
export FORAGERR_ADMIN_USER="${FORAGERR_ADMIN_USER:-admin}"
export FORAGERR_ADMIN_PASSWORD="${FORAGERR_ADMIN_PASSWORD:-readme-shots-admin}"

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

# --- Stale-port guard --------------------------------------------------------
# If something already answers on ${BASE_URL}, we would otherwise capture that
# unknown instance (wrong library, wrong build) or fail confusingly. Refuse to
# proceed unless the operator opts in to reusing it.
if curl -fsS "${BASE_URL}/health" >/dev/null 2>&1; then
  if [ "${FORAGERR_REFRESH_REUSE:-}" = "1" ]; then
    log "reusing the instance already running on ${BASE_URL} (FORAGERR_REFRESH_REUSE=1)"
    REUSING=1
  else
    fail "something is already serving ${BASE_URL} — stop that instance first, or set FORAGERR_REFRESH_REUSE=1 to intentionally reuse it"
  fi
fi

# --- Start the backend against the demo library ------------------------------
if [ "${REUSING:-}" != "1" ]; then
  export FORAGERR_CONFIG_DIR="${CONFIG_DIR}"
  # The keystore requires a passphrase at startup (FRG-AUTH-011); this is a
  # throwaway capture instance in a temp config dir with no stored secrets, so a
  # fixed hermetic value suffices (same posture as e2e/compose.yaml).
  export FORAGERR_SECRET_KEY="${FORAGERR_SECRET_KEY:-readme-shots-capture-passphrase}"
  export FORAGERR_HOST=127.0.0.1
  export FORAGERR_PORT="${PORT}"
  export FORAGERR_LOG_LEVEL=WARNING
  export FORAGERR_LIBRARY_IMPORT_MODE=move
  export FORAGERR_STATIC_DIR="${REPO}/frontend/dist"
  # The weekly-pull source is ON by default (pull-enabled-default): pin it OFF
  # for the capture instance so shots never depend on a third-party's uptime
  # (same hermetic posture as e2e/compose.yaml).
  export FORAGERR_PULL_ENABLED=false

  log "starting backend on ${BASE_URL}…"
  ( cd "${REPO}/backend" && exec uv run foragerr ) &
  BACKEND_PID=$!

  for _ in $(seq 1 60); do
    if curl -fsS "${BASE_URL}/health" >/dev/null 2>&1; then break; fi
    sleep 1
  done
  curl -fsS "${BASE_URL}/health" >/dev/null 2>&1 || fail "backend did not become healthy"
fi

# --- Authenticate (mandatory login, M8 auth) ---------------------------------
# Log in once to a cookie jar, then route every API call through `apic`, which
# adds the session cookie plus a same-origin Origin header — the perimeter
# refuses cookie-authed unsafe methods whose Origin doesn't match its own
# (FRG-SEC-005), and a bare curl sends none.
log "authenticating as ${FORAGERR_ADMIN_USER}…"
# Build the login body in a subprocess that reads the creds from the
# environment and pipe it to curl over stdin (--data-binary @-). The password
# therefore never appears in any process's argv (visible via ps/proc to other
# local users) — only in this script's own environment. Matters for the
# FORAGERR_REFRESH_REUSE path, where these can be a real operator's creds.
python3 -c 'import json, os; print(json.dumps({"username": os.environ["FORAGERR_ADMIN_USER"], "password": os.environ["FORAGERR_ADMIN_PASSWORD"]}))' \
  | curl -fsS -c "${JAR}" -X POST "${BASE_URL}/api/v1/auth/login" \
      -H 'content-type: application/json' -H "Origin: ${BASE_URL}" \
      --data-binary @- >/dev/null \
  || fail "login failed — is the admin bootstrap pair set and correct?"
apic() { curl -fsS -b "${JAR}" -H "Origin: ${BASE_URL}" "$@"; }

# --- Populate the library if empty (register /comics, then library-import) ---
series_count() {
  apic "${BASE_URL}/api/v1/series?page=1&pageSize=1" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("totalRecords",0))'
}

if [ "$(series_count)" -eq 0 ]; then
  log "library empty — importing ${COMICS_DIR}"
  [ -d "${COMICS_DIR}" ] || fail "demo library ${COMICS_DIR} does not exist"

  # Build the request body with json.dumps so a COMICS_DIR containing quotes,
  # backslashes, or other JSON-significant characters cannot corrupt the payload.
  ROOT_BODY="$(COMICS_DIR="${COMICS_DIR}" python3 -c 'import json,os; print(json.dumps({"path": os.environ["COMICS_DIR"]}))')"
  ROOT_ID="$(apic -X POST "${BASE_URL}/api/v1/rootfolder" \
    -H 'content-type: application/json' -d "${ROOT_BODY}" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"

  apic -X POST "${BASE_URL}/api/v1/library-import/scan" \
    -H 'content-type: application/json' -d "{\"rootFolderId\":${ROOT_ID}}" >/dev/null

  # Wait for the scan to stage groups with a ComicVine proposal.
  # Wait until the staged-with-proposal set is non-empty AND stable across
  # two consecutive polls — breaking on the first staged group races the
  # scan and imports a partial library.
  GROUP_IDS=""
  PREV=""
  for _ in $(seq 1 60); do
    GROUP_IDS="$(apic "${BASE_URL}/api/v1/library-import?rootFolderId=${ROOT_ID}" \
      | python3 -c 'import json,sys
d=json.load(sys.stdin)
ids=sorted(g["id"] for g in d.get("records",[]) if g.get("proposedCvVolumeId"))
print(",".join(str(i) for i in ids))')"
    if [ -n "${GROUP_IDS}" ] && [ "${GROUP_IDS}" = "${PREV}" ]; then
      break
    fi
    PREV="${GROUP_IDS}"
    sleep 3
  done
  [ -n "${GROUP_IDS}" ] && [ "${GROUP_IDS}" = "${PREV}" ] \
    || fail "library-import staging did not stabilize"

  # Import completeness: every staged group must carry a ComicVine proposal. A
  # partial tour (some folders silently dropped for want of a match) must not
  # ship — fail loudly, naming the unproposed folders so the operator can fix
  # the metadata or exclude them deliberately.
  UNPROPOSED="$(apic "${BASE_URL}/api/v1/library-import?rootFolderId=${ROOT_ID}" \
    | python3 -c 'import json,sys
d=json.load(sys.stdin)
names=[g.get("folder","?") for g in d.get("records",[]) if not g.get("proposedCvVolumeId")]
print("\n".join(names))')"
  [ -z "${UNPROPOSED}" ] \
    || fail "$(printf "%s staged group(s) lack a ComicVine proposal:\n%s" \
              "$(echo "${UNPROPOSED}" | grep -c .)" "${UNPROPOSED}")"

  # Known demo-library proposal overrides: the auto-match is wrong for some
  # golden-age titles (ComicVine has same-name modern reprint volumes), which
  # would silently poison the tour. folder-name -> ComicVine volume id.
  # Planet Comics (1940, Fiction House) = CV volume 816 (auto-match picks the
  # 1988 Blackthorne reprint).
  declare -A CV_OVERRIDES=( ["Planet Comics"]=816 )
  GROUPS_JSON="$(apic "${BASE_URL}/api/v1/library-import?rootFolderId=${ROOT_ID}")"
  for folder in "${!CV_OVERRIDES[@]}"; do
    GID="$(echo "${GROUPS_JSON}" | python3 -c 'import json,sys
folder=sys.argv[1]
for g in json.load(sys.stdin).get("records",[]):
    if folder in g.get("folder",""):
        print(g["id"]); break' "${folder}")"
    [ -n "${GID}" ] || fail "override target '${folder}' not found among staged groups — a silent miss would reproduce the wrong-volume bug"
    log "overriding ${folder} -> CV volume ${CV_OVERRIDES[$folder]}"
    apic -X PATCH "${BASE_URL}/api/v1/library-import/groups/${GID}" \
      -H 'content-type: application/json' \
      -d "{\"cvVolumeId\":${CV_OVERRIDES[$folder]}}" >/dev/null \
      || fail "override for ${folder} failed"
  done

  IDS_JSON="[$(echo "${GROUP_IDS}" | sed 's/,/, /g')]"
  apic -X POST "${BASE_URL}/api/v1/library-import/execute" \
    -H 'content-type: application/json' \
    -d "{\"groupIds\":${IDS_JSON},\"addOptions\":{\"monitorStrategy\":\"all\",\"monitorNewItems\":\"all\",\"formatProfileId\":null,\"searchOnAdd\":false}}" \
    >/dev/null || fail "library-import execute failed"

  # Give the chained refresh/scan a moment to land covers + issues.
  EXPECTED="$(echo "${GROUP_IDS}" | awk -F, '{print NF}')"
  # Import-chained refreshes now include up to credits_fetch_per_refresh
  # (default 25) rate-gated per-issue credit detail fetches each
  # (m5-credits-live-fetch): ~50s extra per series through the single 2s
  # gate, serialized. Budget ~2.5 min per series rather than the old 3 min
  # total, or a large final series (Fables) times the whole run out at 5/6.
  for _ in $(seq 1 $((EXPECTED * 75))); do
    [ "$(series_count)" -ge "${EXPECTED}" ] && break
    sleep 2
  done
  [ "$(series_count)" -ge "${EXPECTED}" ] \
    || fail "import finished with $(series_count)/${EXPECTED} series"
fi
log "library has $(series_count) series"

# Let the post-import churn settle: cover downloads and metadata jobs run
# right after an import and have crashed the capture renderer when raced.
log "waiting for command queue to drain…"
for _ in $(seq 1 60); do
  BUSY="$(apic "${BASE_URL}/api/v1/command?state=running" 2>/dev/null \
    | python3 -c 'import json,sys
try: print(len(json.load(sys.stdin).get("records",[])))
except Exception: print(0)')"
  [ "${BUSY}" = "0" ] && break
  sleep 2
done

# --- Capture -----------------------------------------------------------------
# This sandbox's node lacks TypeScript type-stripping, so transpile then run
# (the fallback documented in capture-readme-shots.ts's header).
log "capturing screenshots…"
CAP_OUT="$(mktemp -d "${TMPDIR:-/tmp}/foragerr-capture.XXXXXX")"
( cd "${REPO}/e2e" \
  && node_modules/.bin/tsc --ignoreConfig --noCheck --module nodenext --target es2022 \
       --moduleResolution nodenext \
       --outDir "${CAP_OUT}" scripts/capture-readme-shots.ts \
  && ln -sfn "${REPO}/e2e/node_modules" "${CAP_OUT}/node_modules" ) \
  || fail "capture transpile failed"
# One retry: headless renderer crashes are environmental (tight /dev/shm,
# concurrent load) — a second attempt distinguishes flake from real failure.
CAPTURED=0
for attempt in 1 2; do
  if BASE_URL="${BASE_URL}" OUT_DIR="${ASSET_DIR}" node "${CAP_OUT}/capture-readme-shots.js"; then
    CAPTURED=1; break
  fi
  log "capture attempt ${attempt} failed$( [ "${attempt}" = 1 ] && echo '; retrying' )"
  sleep 5
done
[ "${CAPTURED}" = 1 ] || fail "capture script failed twice"
rm -rf "${CAP_OUT}"

# --- Optimize: quantize each PNG down to the budget --------------------------
log "optimizing PNGs to <=${BUDGET} bytes…"
# Pillow lives in the backend venv (it is a runtime dependency there);
# ambient python3 may not have it.
PYBIN="${REPO}/backend/.venv/bin/python"
[ -x "${PYBIN}" ] || PYBIN=python3
"${PYBIN}" - "${ASSET_DIR}" "${BUDGET}" "${SHOTS[@]}" <<'PY'
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
