#!/usr/bin/env bash
# One-command hermetic end-to-end run for foragerr (FRG-PROC-010).
#
#   build the real image -> generate fixtures (CA/cert, cbz) -> compose up ->
#   wait /health -> seed a root folder -> playwright test -> generate
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
# Comfortably above BOTH floors: the DDL verify floor (10 KiB) and the importer's
# sample/junk floor (100 KiB) — a real comic archive is well over both.
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
    z.writestr("001.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 200_000)
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

# --- 5. seed a root folder (no create API in M1) ----------------------------
echo "==> seeding root folder /library"
"${COMPOSE[@]}" exec -T foragerr python - <<'PY'
import sqlite3
c = sqlite3.connect("/config/foragerr.db", timeout=15)
c.execute("PRAGMA busy_timeout=15000")
c.execute("INSERT OR IGNORE INTO root_folders(path) VALUES (?)", ("/library",))
c.commit()
c.close()
print("root folder seeded")
PY

# --- 6. run the suite --------------------------------------------------------
echo "==> playwright test"
cd "${HERE}"
set +e
npx playwright test "$@"
PW_EXIT=$?
set -e

# --- 7. generate the acceptance report --------------------------------------
echo "==> generating acceptance-report.md"
node "${HERE}/scripts/acceptance-report.mjs" \
  "${HERE}/results/results.json" "${HERE}/acceptance-report.md" || true

if [ "${PW_EXIT}" -ne 0 ]; then
  echo "!! e2e FAILED (see e2e/acceptance-report.md and results/html)" >&2
fi
exit "${PW_EXIT}"
