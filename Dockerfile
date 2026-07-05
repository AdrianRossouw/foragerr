# foragerr — single image, linuxserver.io conventions (FRG-DEP-001).
#
# Stage 1 builds the React SPA (node). Stage 2 is a python-slim runtime that
# uv-installs the backend and serves the built SPA statically from FastAPI, so
# one container answers "/" (SPA), "/api", "/opds" and "/health" on port 8789.
#
# linuxserver-style contract (design decision 5, "s6-compatible" = the PUID/PGID
# + init-script contract, not a full s6 supervision tree): the entrypoint remaps
# an unprivileged "abc" user to the requested PUID/PGID, applies TZ, fixes
# ownership of the single /config state volume, then drops privileges (gosu) and
# execs the app. See docker/entrypoint.sh.

# ---------------------------------------------------------------------------
# Stage 1: build the frontend SPA
# ---------------------------------------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /build

# Install deps against the lockfile first for layer caching.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Build the static bundle -> /build/dist
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: python runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# uv, copied from its official image (no curl-pipe install).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Runtime OS deps: gosu (privilege drop), curl (HEALTHCHECK), tzdata (TZ),
# passwd (usermod/groupmod for PUID/PGID remap). Kept minimal; caches removed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gosu \
        curl \
        tzdata \
        passwd \
    && rm -rf /var/lib/apt/lists/*

# Unprivileged runtime user (linuxserver convention: "abc", default 911:911).
# The entrypoint remaps these to the caller's PUID/PGID at start.
RUN groupadd -g 911 abc \
    && useradd -u 911 -g abc -d /config -s /usr/sbin/nologin abc

WORKDIR /app

# Install the backend into an in-image venv against the lockfile (reproducible).
# Copy dependency metadata first for layer caching, then the source.
ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv
COPY backend/pyproject.toml backend/uv.lock ./
COPY backend/src ./src
RUN uv sync --frozen --no-dev --no-editable

# The built SPA (served by FastAPI at "/").
COPY --from=frontend /build/dist /app/static

# Entrypoint (root: remap user, chown /config, drop privileges).
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Defaults: all persistent state under /config, SPA served from /app/static,
# bind all interfaces inside the container (network exposure is scoped by the
# operator to the tailnet — see docs/manual/admin/deployment.md / RISK-020).
ENV PATH="/app/.venv/bin:$PATH" \
    FORAGERR_CONFIG_DIR=/config \
    FORAGERR_STATIC_DIR=/app/static \
    FORAGERR_HOST=0.0.0.0 \
    FORAGERR_PORT=8789 \
    PUID=911 \
    PGID=911 \
    TZ=Etc/UTC

VOLUME /config
EXPOSE 8789

# Docker probes the same unauthenticated endpoint the spec designs for it.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8789/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["foragerr"]
