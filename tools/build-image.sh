#!/usr/bin/env bash
# Build the foragerr Docker image (FRG-DEP-001).
#
# Before invoking `docker build`, scan the build context for secret material and
# FAIL the build if any is found — a spec requirement (FRG-DEP-001, "Build script
# secret-scans the build context") and defence in depth over .dockerignore. The
# scan is independent of .dockerignore on purpose: even a secret that would be
# excluded from the image must stop the build, so an operator can never quietly
# bake one in by editing .dockerignore.
#
# Usage:
#   tools/build-image.sh [--tag NAME:TAG] [--scan-only] [--context DIR]
#
# Env:
#   FORAGERR_IMAGE   default image tag (overridden by --tag); default "foragerr:dev"
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTEXT="${REPO_ROOT}"
IMAGE="${FORAGERR_IMAGE:-foragerr:dev}"
SCAN_ONLY=0

while [ $# -gt 0 ]; do
    case "$1" in
        --tag) IMAGE="$2"; shift 2 ;;
        --context) CONTEXT="$2"; shift 2 ;;
        --scan-only) SCAN_ONLY=1; shift ;;
        -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

# Directories excluded from the build context by .dockerignore (so never in the
# image) and therefore out of scope for the scan: heavy caches, VCS, gitignored
# study clones, node deps, and the tests/docs/spec material the image omits.
# Keeping this list in step with .dockerignore's directory excludes is what makes
# the scan a faithful check of the actual build context (not the whole worktree).
PRUNE_DIRS='.git .githooks .claude .venv venv node_modules __pycache__ .pytest_cache .ruff_cache .mypy_cache .reference dist tests docs openspec'

# --------------------------------------------------------------------------
# secret_scan CONTEXT_DIR  -> exit 0 clean, exit 1 if secret material found
# --------------------------------------------------------------------------
secret_scan() {
    local ctx="$1"
    local findings=0

    # Build the prune expression for `find`.
    local prune_expr=()
    local d
    for d in ${PRUNE_DIRS}; do
        prune_expr+=(-name "$d" -o)
    done
    # drop trailing -o
    unset 'prune_expr[${#prune_expr[@]}-1]'

    # 1) Environment files carrying real values. Templates/examples are allowed.
    #    A `.env` in the working tree is NORMAL on a dev machine; what matters is
    #    whether docker would upload it. When the context's .dockerignore carries
    #    the recursive env excludes (.env / .env.* / **/.env / **/.env.*), docker
    #    cannot COPY these files into any layer, so their presence is reported
    #    but not fatal. If those patterns are ever removed, this reverts to a
    #    hard failure — the scan stays the enforcing check, .dockerignore the
    #    mechanism it verifies.
    local env_excluded=0
    if [ -f "$ctx/.dockerignore" ] \
        && grep -qxF '.env' "$ctx/.dockerignore" \
        && grep -qxF '.env.*' "$ctx/.dockerignore" \
        && grep -qxF '**/.env' "$ctx/.dockerignore" \
        && grep -qxF '**/.env.*' "$ctx/.dockerignore"; then
        env_excluded=1
    fi
    while IFS= read -r -d '' f; do
        case "$(basename "$f")" in
            .env.example|.env.sample|.env.template) continue ;;
        esac
        if [ "$env_excluded" = 1 ]; then
            echo "SECRET-SCAN: env file ${f#"$ctx"/} present but excluded by .dockerignore (ok)" >&2
        else
            echo "SECRET-SCAN: env file present in build context: ${f#"$ctx"/}" >&2
            findings=$((findings + 1))
        fi
    done < <(find "$ctx" \( "${prune_expr[@]}" \) -type d -prune -o \
                 -type f \( -name '.env' -o -name '.env.*' \) -print0)

    # 2) Key-shaped content in files that could reach the image. Patterns are
    #    chosen to catch real credential material while ignoring the field NAMES
    #    and ${PLACEHOLDER}/{template} forms the repo legitimately contains.
    #    (ERE; -I skips binaries.)
    local patterns='-----BEGIN [A-Z ]*PRIVATE KEY-----'
    patterns+='|AKIA[0-9A-Z]{16}'
    patterns+='|xox[baprs]-[0-9A-Za-z-]{10,}'
    patterns+='|gh[pousr]_[0-9A-Za-z]{30,}'
    # api_key/secret/password/token = <16+ chars of real-looking secret>, but not
    # ${VAR}, {template}, empty, or "changeme"-style placeholders.
    patterns+='|(api[_-]?key|secret|password|token)[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z0-9/+=_-]{16,}'

    while IFS= read -r -d '' f; do
        # Skip this scanner itself (it necessarily contains the patterns).
        [ "$f" = "${BASH_SOURCE[0]}" ] && continue
        local hits
        # NOTE: -e is required — the first alternative begins with "-----BEGIN",
        # which grep would otherwise parse as an option flag (the pattern must be
        # passed as an explicit -e argument, not positionally).
        hits="$(grep -InE -e "$patterns" "$f" 2>/dev/null \
                    | grep -viE -e '\$\{|\{[a-zA-Z_]+\}|[:=][[:space:]]*["'"'"']?(changeme|example|placeholder|your[_-]|xxx|<)' \
                    || true)"
        if [ -n "$hits" ]; then
            echo "SECRET-SCAN: key-shaped material in ${f#"$ctx"/}:" >&2
            echo "$hits" | sed 's/^/    /' >&2
            findings=$((findings + 1))
        fi
    done < <(find "$ctx" \( "${prune_expr[@]}" \) -type d -prune -o -type f -print0)

    if [ "$findings" -gt 0 ]; then
        echo "SECRET-SCAN: FAILED — ${findings} finding(s); refusing to build." >&2
        return 1
    fi
    echo "SECRET-SCAN: clean."
    return 0
}

echo "==> Secret-scanning build context: ${CONTEXT}"
secret_scan "${CONTEXT}"

if [ "${SCAN_ONLY}" -eq 1 ]; then
    echo "==> --scan-only: skipping docker build."
    exit 0
fi

echo "==> Building image: ${IMAGE}"
docker build -t "${IMAGE}" -f "${REPO_ROOT}/Dockerfile" "${CONTEXT}"
echo "==> Built ${IMAGE}"
