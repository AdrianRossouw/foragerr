#!/bin/sh
# foragerr container init (FRG-DEP-001) — linuxserver.io PUID/PGID contract.
#
# Runs as root ONLY to: apply the timezone, remap the unprivileged "abc" user to
# the caller-supplied PUID/PGID, and hand /config to that user. It then drops all
# privileges via gosu and execs the app, so the Python process never runs as root
# and files it writes under /config are owned by PUID:PGID.
#
# "s6-compatible" per design decision 5: this is the init-script contract
# linuxserver images expose (PUID/PGID/TZ + a single writable /config), not a
# full s6 supervision tree.
set -eu

PUID="${PUID:-911}"
PGID="${PGID:-911}"
CONFIG_DIR="${FORAGERR_CONFIG_DIR:-/config}"

# --- Timezone -------------------------------------------------------------
if [ -n "${TZ:-}" ] && [ -f "/usr/share/zoneinfo/${TZ}" ]; then
    ln -snf "/usr/share/zoneinfo/${TZ}" /etc/localtime
    echo "${TZ}" > /etc/timezone
fi

# --- Remap the runtime user to the requested PUID/PGID --------------------
# -o allows a non-unique id (harmless in a single-user container) so any
# host UID/GID the operator supplies is accepted.
if [ "$(id -g abc)" != "${PGID}" ]; then
    groupmod -o -g "${PGID}" abc
fi
if [ "$(id -u abc)" != "${PUID}" ]; then
    usermod -o -u "${PUID}" abc
fi

# --- /config ownership ----------------------------------------------------
# The single state volume must be writable by the runtime user. Chown the
# directory and anything in it not already owned by PUID (bounded: /config
# holds only app state, never the media library). Media/download mounts are
# deliberately NOT touched here.
mkdir -p "${CONFIG_DIR}"
chown "${PUID}:${PGID}" "${CONFIG_DIR}"
find "${CONFIG_DIR}" ! -user "${PUID}" -exec chown "${PUID}:${PGID}" {} + 2>/dev/null || true

echo "foragerr: starting as ${PUID}:${PGID}, config=${CONFIG_DIR}, tz=${TZ:-unset}"

# --- Drop privileges and exec --------------------------------------------
exec gosu "${PUID}:${PGID}" "$@"
