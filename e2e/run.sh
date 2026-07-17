#!/usr/bin/env bash
# One-command hermetic end-to-end run for foragerr (FRG-PROC-010).
#
#   build the real image -> generate fixtures (CA/cert, cbz) -> compose up ->
#   wait /health -> register the root folder via the API -> playwright test ->
#   generate
#   e2e/acceptance-report.md -> compose down.
#
# Exit code propagates: non-zero when any scenario fails (Playwright's own exit),
# and the generated acceptance report names the failed scenario(s).
#
# Env:
#   FORAGERR_IMAGE   image tag to build/test (default foragerr:e2e)
#   E2E_KEEP_UP=1    leave the stack running (skip compose down) for debugging
#   E2E_SKIP_BUILD=1 reuse an already-built FORAGERR_IMAGE
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/.." && pwd)"
export FORAGERR_IMAGE="${FORAGERR_IMAGE:-foragerr:e2e}"

COMPOSE=(docker compose -f "${HERE}/compose.yaml" -p foragerr-e2e)

# Run-scoped scratch OUTSIDE the repo (keeps the build-context secret scan and
# git status clean; certs/keys never touch the tree).
RUN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/foragerr-e2e.XXXXXX")"
export FORAGERR_E2E_RUN="${RUN_DIR}"
export FORAGERR_PUID="$(id -u)"
export FORAGERR_PGID="$(id -g)"

# Mandatory-auth bootstrap fixtures (FRG-AUTH-002). FIXED non-secret test
# credentials — a throwaway hermetic admin account, never real secrets. compose
# interpolates the same defaults into the app's env; the Playwright specs read
# these to drive the login form and Basic checks. Exported so both see one
# source of truth.
export FORAGERR_ADMIN_USER="${FORAGERR_ADMIN_USER:-e2e-admin}"
export FORAGERR_ADMIN_PASSWORD="${FORAGERR_ADMIN_PASSWORD:-e2e-admin-pw-9c3f2a1b}"

cleanup() {
  local code=$?
  if [ "${E2E_KEEP_UP:-0}" != "1" ]; then
    "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
    rm -rf "${RUN_DIR}" || true
  else
    echo "==> E2E_KEEP_UP=1: stack left running; run dir ${RUN_DIR}"
  fi
  exit "${code}"
}
trap cleanup EXIT

echo "==> run dir: ${RUN_DIR}"
mkdir -p "${RUN_DIR}"/{config,library,certs,data}
chmod -R 777 "${RUN_DIR}"

# --- 1. build the real image under test -------------------------------------
if [ "${E2E_SKIP_BUILD:-0}" != "1" ]; then
  echo "==> building ${FORAGERR_IMAGE}"
  bash "${REPO_ROOT}/tools/build-image.sh" --tag "${FORAGERR_IMAGE}"
fi

# --- 2. fixtures: TLS CA + getcomics.org leaf, and the canonical cbz ---------
echo "==> generating fixture TLS material + cbz"
CERTS="${RUN_DIR}/certs"
openssl req -x509 -newkey rsa:2048 -nodes -keyout "${CERTS}/ca.key" \
  -out "${CERTS}/ca.pem" -subj "/CN=foragerr-e2e-ca" -days 2 >/dev/null 2>&1
openssl req -newkey rsa:2048 -nodes -keyout "${CERTS}/getcomics.key" \
  -out "${CERTS}/getcomics.csr" -subj "/CN=getcomics.org" >/dev/null 2>&1
openssl x509 -req -in "${CERTS}/getcomics.csr" -CA "${CERTS}/ca.pem" \
  -CAkey "${CERTS}/ca.key" -CAcreateserial -out "${CERTS}/getcomics.crt" \
  -days 2 -extfile <(printf "subjectAltName=DNS:getcomics.org\n") >/dev/null 2>&1

# The single source of truth for the byte-identity assertion: the app downloads
# this, imports it, and OPDS serves it back; the spec compares against this file.
python3 - "${RUN_DIR}/data/saga-001.cbz" <<'PY'
import io, sys, zipfile
from PIL import Image
# A REAL decodable JPEG page — the OPDS per-issue cover render (FRG-OPDS-020)
# extracts and decodes page 0, so the fixture's first page must be a genuine
# image, not magic-bytes-plus-zeros. Noise so it compresses large; padded past
# BOTH floors (DDL verify 10 KiB, importer sample/junk 100 KiB). Trailing zeros
# after the JPEG EOI are ignored by decoders, so the page still renders.
page = io.BytesIO()
Image.effect_noise((800, 1200), 64).convert("RGB").save(page, "JPEG", quality=80)
member = page.getvalue()
if len(member) < 200_000:
    member += b"\x00" * (200_000 - len(member))
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
    z.writestr("001.jpg", member)
open(sys.argv[1], "wb").write(buf.getvalue())
PY
chmod -R 777 "${RUN_DIR}"

# --- 3. bring the stack up ---------------------------------------------------
echo "==> compose build + up"
"${COMPOSE[@]}" build >/dev/null
"${COMPOSE[@]}" up -d

# Discover the ephemeral host port compose assigned to the app.
HOSTPORT=""
for _ in $(seq 1 30); do
  mapping="$("${COMPOSE[@]}" port foragerr 8789 2>/dev/null || true)"
  HOSTPORT="${mapping##*:}"
  [ -n "${HOSTPORT}" ] && break
  sleep 1
done
if [ -z "${HOSTPORT}" ]; then
  echo "!! could not determine mapped host port for foragerr:8789" >&2
  "${COMPOSE[@]}" logs foragerr || true
  exit 3
fi
export FORAGERR_BASE_URL="http://127.0.0.1:${HOSTPORT}"
# The container id the restart-resilience scenario (S8) restarts.
export E2E_APP_CONTAINER="$("${COMPOSE[@]}" ps -q foragerr)"
echo "==> app base URL: ${FORAGERR_BASE_URL} (container ${E2E_APP_CONTAINER})"

# --- 4. wait for health ------------------------------------------------------
echo "==> waiting for /health"
healthy=0
for _ in $(seq 1 60); do
  if curl -fsS "${FORAGERR_BASE_URL}/health" >/dev/null 2>&1; then
    healthy=1
    break
  fi
  sleep 2
done
if [ "${healthy}" != "1" ]; then
  echo "!! app never became healthy" >&2
  "${COMPOSE[@]}" logs foragerr || true
  exit 3
fi

# --- 4b. authenticate: log in, then retrieve the bootstrap API key ONCE ------
# The stack now enforces mandatory auth (FRG-AUTH-010): every API call needs a
# credential. Log in with the fixture admin (the one perimeter-exempt door) to a
# cookie jar, then read the seeded API key exactly once via the authenticated
# POST /api/v1/auth/bootstrap-key. It is a POST (the read consumes the one-time
# key — a state change), so under cookie auth it carries the FRG-SEC-005 Origin
# check: send a matching Origin. The key is stored SHA-256 in the DB and stays
# valid for the whole run, so the setup script + every spec reach the app with
# the CSRF-immune X-Api-Key header; the browser projects log in separately
# (auth.setup.ts) for their session cookie.
echo "==> logging in and retrieving the bootstrap API key"
COOKIE_JAR="${RUN_DIR}/cookies.txt"
login_status="$(curl -sS -o "${RUN_DIR}/login.json" -w '%{http_code}' \
  -c "${COOKIE_JAR}" \
  -X POST "${FORAGERR_BASE_URL}/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"username\": \"${FORAGERR_ADMIN_USER}\", \"password\": \"${FORAGERR_ADMIN_PASSWORD}\", \"remember\": false}")"
if [ "${login_status}" != "200" ]; then
  echo "!! admin login failed (HTTP ${login_status}):" >&2
  cat "${RUN_DIR}/login.json" >&2 || true
  "${COMPOSE[@]}" logs foragerr || true
  exit 3
fi
key_status="$(curl -sS -o "${RUN_DIR}/bootstrap-key.json" -w '%{http_code}' \
  -b "${COOKIE_JAR}" \
  -X POST \
  -H "Origin: ${FORAGERR_BASE_URL}" \
  "${FORAGERR_BASE_URL}/api/v1/auth/bootstrap-key")"
if [ "${key_status}" != "200" ]; then
  echo "!! bootstrap-key retrieval failed (HTTP ${key_status}):" >&2
  cat "${RUN_DIR}/bootstrap-key.json" >&2 || true
  exit 3
fi
E2E_API_KEY="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["api_key"])' "${RUN_DIR}/bootstrap-key.json")"
if [ -z "${E2E_API_KEY}" ]; then
  echo "!! bootstrap-key response carried no api_key" >&2
  exit 3
fi
export E2E_API_KEY
echo "bootstrap API key retrieved (used via X-Api-Key for the rest of the run)"

# --- 5. register the root folder through the real API (FRG-SER-008) ---------
# First-run registration end-to-end: POST /api/v1/rootfolder replaces the old
# direct sqlite INSERT (there was no create API in M1). Idempotent across
# re-runs against a kept-up stack: a duplicate registration is a 400 naming
# "already registered" — tolerated, anything else is fatal. Authenticated with
# the API key: the X-Api-Key surface is exempt from the CSRF Origin check, so no
# Origin header is needed on this unsafe method.
echo "==> registering root folder /library via POST /api/v1/rootfolder"
seed_status="$(curl -sS -o "${RUN_DIR}/rootfolder-seed.json" -w '%{http_code}' \
  -X POST "${FORAGERR_BASE_URL}/api/v1/rootfolder" \
  -H 'Content-Type: application/json' \
  -H "X-Api-Key: ${E2E_API_KEY}" \
  -d '{"path": "/library"}')"
case "${seed_status}" in
  201)
    echo "root folder registered"
    ;;
  400)
    if grep -q "already registered" "${RUN_DIR}/rootfolder-seed.json"; then
      echo "root folder already registered (re-run) — continuing"
    else
      echo "!! root folder registration rejected:" >&2
      cat "${RUN_DIR}/rootfolder-seed.json" >&2
      exit 3
    fi
    ;;
  *)
    echo "!! root folder registration failed (HTTP ${seed_status}):" >&2
    cat "${RUN_DIR}/rootfolder-seed.json" >&2 || true
    exit 3
    ;;
esac

# --- 6. run the suite --------------------------------------------------------
# Clear any prior run's artifacts FIRST: a crashed Playwright must never be able
# to leave a stale (possibly GREEN) results.json or acceptance-report.md in
# place for the generator to re-emit. Playwright recreates results/ itself.
echo "==> clearing stale results + report"
rm -rf "${HERE}/results" "${HERE}/acceptance-report.md"

# Bootstrap: "one command" includes a fresh checkout — install the harness's
# own deps and browser if absent (both are gitignored artifacts; the install
# command is an idempotent fast no-op when the browser is already present).
if [ ! -d "${HERE}/node_modules" ]; then
    echo "==> npm ci (e2e harness deps)"
    (cd "${HERE}" && npm ci)
fi
(cd "${HERE}" && npx playwright install chromium)

echo "==> playwright test"
cd "${HERE}"
set +e
npx playwright test "$@"
PW_EXIT=$?
set -e

# --- 7. generate the acceptance report --------------------------------------
# No `|| true`: if results.json is missing/unparseable (crash/interrupt), the
# generator writes an explicit RED "run did not produce results" report and
# exits non-zero. Capture that so run.sh fails even if Playwright returned 0.
echo "==> generating acceptance-report.md"
GEN_EXIT=0
node "${HERE}/scripts/acceptance-report.mjs" \
  "${HERE}/results/results.json" "${HERE}/acceptance-report.md" || GEN_EXIT=$?

# Preserve Playwright's exit-code propagation first; a scenario failure is the
# most specific signal and the report already names it.
if [ "${PW_EXIT}" -ne 0 ]; then
  echo "!! e2e FAILED (see e2e/acceptance-report.md and results/html)" >&2
  exit "${PW_EXIT}"
fi
# Playwright passed but the report is RED (no results / not-run) — still a failure.
if [ "${GEN_EXIT}" -ne 0 ]; then
  echo "!! e2e report is RED: run did not produce a clean results set" >&2
  exit "${GEN_EXIT}"
fi
