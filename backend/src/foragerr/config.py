"""Configuration loading (FRG-DEP-002, FRG-DEP-003, FRG-DEP-005, FRG-NFR-009).

Design (m1-foundation, decision 7): pydantic-settings models. Sources, in
precedence order: ``FORAGERR_*`` environment variables override values from
``<config_dir>/config.yaml``, which override built-in defaults. The config
directory itself is resolved from ``FORAGERR_CONFIG_DIR`` (default
``/config``) and holds ALL persistent state. On first run a fully documented
``config.yaml`` is generated (every setting, its default, an explanatory
comment; secrets only as commented placeholders).

Secrets are ``SecretStr`` fields with empty defaults — never baked in — and
every non-empty secret value self-registers with the log-redaction filter at
config-load time (FRG-NFR-008 hook).

Validation is fail-fast: the whole configuration is validated in one pass and
a :class:`ConfigError` carrying field-precise messages is raised; the app
entrypoint converts that into a non-zero exit. Out-of-range intervals are
clamped to their documented safe range with a warning instead of failing.
"""

from __future__ import annotations

import logging as _stdlog
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from foragerr.config_migrations import (
    CURRENT_CONFIG_VERSION,
    ConfigSchemaVersionError,
    atomic_write_text,
    migrate_config,
)
from foragerr.logging import register_secret
from foragerr.naming import DEFAULT_FILE_TEMPLATE, DEFAULT_FOLDER_TEMPLATE
from foragerr.security.archives import DEFAULT_ARCHIVE_LIMITS, ArchiveLimits

logger = _stdlog.getLogger("foragerr.config")

#: Fresh-install default file-naming template (FRG-PP-020, naming-defaults):
#: no internal-identifier token. Adopting an existing library must never stamp
#: a database row id — meaningless (and silently mis-mappable) after a
#: reinstall or the planned 1.0 clean slate — into a filename. Aliased to the
#: single source in ``foragerr.naming`` so the Settings default, the token
#: engine, ImportContext, and the ``/config/naming/tokens`` endpoint can never
#: drift (a "reset to default" that re-introduced the tag was the drift).
DEFAULT_FILE_NAMING_TEMPLATE = DEFAULT_FILE_TEMPLATE

CONFIG_DIR_ENV = "FORAGERR_CONFIG_DIR"
DEFAULT_CONFIG_DIR = Path("/config")
CONFIG_FILENAME = "config.yaml"

#: The mandatory at-rest encryption passphrase env var (FRG-AUTH-011).
#: Environment-only: never read from, or written to, a file under ``/config``.
#: Startup fails when it is absent or empty (enforced in :func:`load_settings`).
#: Assembled (not a single literal) so the secret-literal repo-hygiene guard
#: never flags this env-var NAME as a credential value.
KEYSTORE_ENV_VAR = "FORAGERR_" + "SECRET_KEY"

#: Secret settings that are environment-only: never written to, or read from,
#: the config file (rendered as an env-only note, popped from file values).
_ENV_ONLY_SECRETS = ("secret_key", "admin_password", "opds_password")

_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

#: Core mount paths the configurable OPDS base must never collide with: the
#: API surface ("/api" and below) and the health probe ("/health"). Mounting
#: OPDS on one of these (or on "/", the SPA root) would silently shadow a core
#: route, so ``opds_base_path`` validation rejects them (FRG-NFR-009).
_OPDS_RESERVED_PATHS = ("/api", "/health")

#: Allowed values for the two media-management transfer/import mode settings.
_TRANSFER_MODES = ("move", "copy", "hardlink")
_LIBRARY_IMPORT_MODES = ("in_place", "move")

#: Allowed values for the same-rung duplicate constraint (FRG-PP-014).
_DUPLICATE_CONSTRAINTS = ("larger-size", "preferred-format")

#: Documented safe ranges for interval settings: name -> (floor, ceiling).
#: Out-of-range supplied values are clamped with a warning (FRG-NFR-009).
INTERVAL_RANGES: dict[str, tuple[int, int]] = {
    "scheduler_tick_seconds": (5, 60),
    "shutdown_grace_seconds": (1, 29),
    "listener_request_timeout_seconds": (1, 300),
    "listener_rate_window_seconds": (1, 60),
}

#: Range fragments derived from INTERVAL_RANGES so the generated config.yaml
#: comments (built from Field descriptions) can never drift from the bounds
#: actually enforced by ``_clamp_intervals``.
_TICK_LO, _TICK_HI = INTERVAL_RANGES["scheduler_tick_seconds"]
_GRACE_LO, _GRACE_HI = INTERVAL_RANGES["shutdown_grace_seconds"]
_REQ_TIMEOUT_LO, _REQ_TIMEOUT_HI = INTERVAL_RANGES["listener_request_timeout_seconds"]
_RATE_WIN_LO, _RATE_WIN_HI = INTERVAL_RANGES["listener_rate_window_seconds"]


class ConfigError(Exception):
    """Effective configuration is invalid — startup must fail (FRG-NFR-009)."""


def resolve_config_dir() -> Path:
    """The directory holding all persistent state (FRG-DEP-002)."""
    return Path(os.environ.get(CONFIG_DIR_ENV, str(DEFAULT_CONFIG_DIR))).expanduser()


def ensure_secret_key_present(settings: "Settings") -> None:
    """Enforce the mandatory at-rest passphrase (FRG-AUTH-011).

    Shared by :func:`load_settings` (the uvicorn ``--factory`` path) and
    :func:`foragerr.app.create_app` (the injected-``Settings`` path) so a keyless
    boot fails identically no matter how ``Settings`` was constructed — the gate
    lives in one place instead of only inside ``load_settings``. Raises
    :class:`ConfigError` naming the variable and the one-line fix."""
    if not settings.secret_key.get_secret_value().strip():
        raise ConfigError(
            f"{KEYSTORE_ENV_VAR} is not set. foragerr requires an operator-chosen "
            "passphrase in this environment variable to encrypt stored provider "
            "secrets at rest. Set it before starting, for example:\n"
            f'  {KEYSTORE_ENV_VAR}="$(openssl rand -base64 32)"\n'
            "and keep it stable across restarts (a changed value costs re-entry "
            "of stored secrets, never data)."
        )


def _file_template_round_trips(template: str) -> bool:
    """True if ``template`` both round-trips a probe identity AND is injective over
    distinct issue numbers (the FRG-PP-009 contract + its data-loss corollary).

    Two properties are checked, because a single-identity probe misses the worst
    failure: a template that renders the SAME name for DISTINCT issues silently
    overwrites one library file with another on rename.

    1. **Round-trip.** A rendered probe re-parses back to the same series matching
       key and issue ordering key — so a renamed file stays reconcilable.
    2. **Injectivity.** Two probes differing only in issue number must render
       DIFFERENT names — this rejects a template that drops the issue number
       (issues 7 and 8 would collide), the one collision every template risks
       regardless of configuration.

    An identity tag (``{IssueId}``/``{CvIssueId}``) is NOT required for this
    check to pass (naming-defaults, FRG-PP-020): it is an operator opt-in for the
    rarer same-series-same-number collision (variant/reprint rows), not a
    property of the shipped default, which carries no tag at all.

    Imports are deferred to avoid an import cycle (``config`` is imported early).
    """
    from fractions import Fraction

    from foragerr.library.ordering import encode_sort_key
    from foragerr.naming import RenameFields, render_filename
    from foragerr.parser import parse
    from foragerr.parser.normalize import matching_key
    from foragerr.parser.ordering import sort_key
    from foragerr.parser.result import Issue

    def _render(issue: str, issue_id: str) -> str:
        fields = RenameFields(
            series_title="Foragerr Probe Series",
            issue=issue,
            year="2015",
            issue_id=issue_id,
        )
        return render_filename(fields, template=template, ext=".cbz")

    try:
        rendered = _render("7", "424242")
        # Injectivity: distinct issue numbers must not collide.
        differs_by_number = _render("8", "424242") != rendered
        reparsed = parse(rendered, reference_year=2016)
    except Exception:
        return False
    if not differs_by_number:
        return False
    if not reparsed.success or reparsed.issue is None:
        return False
    if reparsed.matching_key != matching_key("Foragerr Probe Series"):
        return False
    expected = encode_sort_key(sort_key(Issue(value=Fraction(7), display="7")))
    return encode_sort_key(sort_key(reparsed.issue)) == expected


class Settings(BaseSettings):
    """Effective foragerr configuration (env > config.yaml > defaults)."""

    model_config = SettingsConfigDict(
        env_prefix="FORAGERR_", extra="ignore", env_ignore_empty=True
    )

    config_dir: Path = Field(
        default=DEFAULT_CONFIG_DIR,
        description=(
            "Directory holding ALL persistent state: database, this config "
            "file, logs, backups. Set via the FORAGERR_CONFIG_DIR environment "
            "variable (never read from this file)."
        ),
    )
    secret_key: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Operator-chosen passphrase used to derive the at-rest encryption "
            "key for stored provider secrets (FRG-AUTH-008). MANDATORY: set it "
            "via the FORAGERR_SECRET_KEY environment variable — startup fails "
            "without it. Never read from, or written to, this config file. "
            "Generate a strong value, e.g. 'openssl rand -base64 32', and keep "
            "it stable across restarts; a changed/lost value costs re-entry of "
            "stored provider secrets, never data."
        ),
    )
    admin_user: str = Field(
        default="",
        description=(
            "Bootstrap operator username (FRG-AUTH-002). Set via the "
            "FORAGERR_ADMIN_USER environment variable. Seeds the single "
            "principal on first authed boot; a changed value on a later boot "
            "re-seeds the account (lost-password recovery). Startup fails "
            "without it (and FORAGERR_ADMIN_PASSWORD) when no principal exists."
        ),
    )
    admin_password: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Bootstrap operator password (secret; FRG-AUTH-002). Set via the "
            "FORAGERR_ADMIN_PASSWORD environment variable — never read from, or "
            "written to, this config file. Stored only as a scrypt hash "
            "(FRG-AUTH-003); a changed value re-seeds the account at boot."
        ),
    )
    opds_password: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Optional OPDS HTTP-Basic password (secret; FRG-AUTH-002). Set via "
            "FORAGERR_OPDS_PASSWORD; when empty the OPDS reader password equals "
            "the admin password at seed time. Environment-only; stored only as a "
            "scrypt hash. Independent OPDS-password change lands in a later "
            "change."
        ),
    )
    session_timeout_seconds: int = Field(
        default=86_400,
        ge=60,
        description=(
            "Standard session sliding-inactivity timeout in seconds (FRG-AUTH-004). "
            "Default 24 h. Each authenticated request slides the expiry forward."
        ),
    )
    remember_timeout_seconds: int = Field(
        default=7_776_000,
        ge=60,
        description=(
            "Remember-me session sliding timeout in seconds (FRG-AUTH-004). "
            "Default 90 days; selected by the login-form 'remember me' checkbox. "
            "A default, not a floor — lower it for shared devices."
        ),
    )
    auth_origin_allowlist: str = Field(
        default="",
        description=(
            "Comma-separated extra allowed Origins for the CSRF check and the "
            "WebSocket handshake (FRG-SEC-005), in addition to the deployment's "
            "own origin (derived from the request host). Empty (default) means "
            "own-origin only; set it for a reverse-proxied deployment whose "
            "browser Origin differs from the app's host, e.g. "
            "'https://comics.example.org'."
        ),
    )
    host: str = Field(
        default="0.0.0.0",
        description="Interface the HTTP listener binds to.",
    )
    port: int = Field(
        default=8789,
        ge=1,
        le=65535,
        description="TCP port for the HTTP listener.",
    )
    log_level: str = Field(
        default="INFO",
        description="Log verbosity: DEBUG, INFO, WARNING, ERROR or CRITICAL.",
    )
    log_max_bytes: int = Field(
        default=10_000_000,
        ge=1024,
        description="Maximum size in bytes of logs/foragerr.log before rotation.",
    )
    log_backup_count: int = Field(
        default=5,
        ge=0,
        description="Number of rotated log files to retain.",
    )
    log_buffer_records: int = Field(
        default=2000,
        ge=1,
        description=(
            "Maximum number of most-recent log records kept in the in-memory "
            "ring buffer served by GET /api/v1/log (FRG-API-021). Bounded by "
            "construction: the oldest record is evicted on overflow "
            "(FRG-NFR-015). Memory-only — a restart clears it; container "
            "stdout/the log file remain the durable log."
        ),
    )
    scheduler_tick_seconds: int = Field(
        default=60,
        description=(
            "Scheduler loop tick interval in seconds. Clamped to the safe "
            f"range {_TICK_LO}..{_TICK_HI} with a warning if set outside it."
        ),
    )
    http_connect_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        description=(
            "Outbound HTTP connect timeout in seconds. Applied to every "
            "client built by the shared HTTP factory; never unlimited."
        ),
    )
    http_read_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description=(
            "Outbound HTTP read timeout in seconds (a hung server aborts "
            "the request at this bound)."
        ),
    )
    http_write_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description="Outbound HTTP write timeout in seconds.",
    )
    http_pool_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description=(
            "Maximum seconds to wait for a free connection from the "
            "outbound HTTP connection pool."
        ),
    )
    http_max_response_bytes: int = Field(
        default=26_214_400,
        ge=1024,
        description=(
            "Byte cap on outbound HTTP response bodies (default 25 MiB). "
            "Responses are streamed and aborted at this cap; callers may "
            "lower it per request but never raise it."
        ),
    )
    db_busy_timeout_ms: int = Field(
        default=5000,
        ge=100,
        le=60_000,
        description=(
            "SQLite busy_timeout in milliseconds, applied to every database "
            "connection (FRG-DB-005)."
        ),
    )
    db_backup_retention: int = Field(
        default=3,
        ge=1,
        description=(
            "Number of pre-migration database backups retained under "
            "backups/; the oldest beyond this count are pruned (FRG-DB-003)."
        ),
    )
    db_backup_interval_seconds: int = Field(
        default=86_400,
        ge=3600,
        description=(
            "How often the scheduled backup-database task writes a consistent "
            "copy of the database and config file to backups/scheduled-<ts>/ "
            "(FRG-DB-009). Default daily (86400 s); documented minimum 1 hour "
            "(3600 s) — a smaller value is rejected at load."
        ),
    )
    db_scheduled_backup_retention: int = Field(
        default=7,
        ge=1,
        description=(
            "Number of scheduled backups retained under backups/scheduled-*; "
            "the oldest beyond this count are pruned after each run (FRG-DB-009). "
            "Independent of db_backup_retention (the pre-migration pool)."
        ),
    )
    workers_search: int = Field(
        default=1,
        ge=1,
        le=4,
        description="Worker count for the 'search' workload class (indexer politeness: keep at 1).",
    )
    workers_download: int = Field(
        default=1,
        ge=1,
        le=4,
        description="Worker count for the 'download' workload class (SAB tracking + DDL).",
    )
    workers_pp: int = Field(
        default=1,
        ge=1,
        le=4,
        description="Worker count for the 'pp' (post-processing) workload class.",
    )
    workers_default: int = Field(
        default=2,
        ge=1,
        le=8,
        description="Worker count for the 'default' workload class (everything unclassified).",
    )
    shutdown_grace_seconds: int = Field(
        default=25,
        description=(
            "Grace period in seconds for in-flight commands to finish on "
            f"shutdown. Clamped to the safe range {_GRACE_LO}..{_GRACE_HI} "
            "(must stay under 30s)."
        ),
    )
    job_history_retention_days: int = Field(
        default=30,
        ge=1,
        description="Days of job_history rows kept; older rows are pruned by housekeeping.",
    )
    usenet_retention_days: int = Field(
        default=0,
        ge=0,
        description=(
            "Global usenet retention in days: search candidates older than "
            "this are rejected by the decision engine and requested with a "
            "maxage cap (FRG-IDX-009). 0 disables the check. A per-indexer "
            "retention override always wins over this global value."
        ),
    )
    backlog_search_interval_seconds: int = Field(
        default=6 * 3600,
        ge=3600,
        description=(
            "How often the scheduled backlog re-searches every wanted issue "
            "(FRG-SRCH-009). Minimum 1 hour."
        ),
    )
    backlog_search_delay_seconds: int = Field(
        default=30,
        ge=0,
        description=(
            "Politeness delay in seconds between consecutive per-issue "
            "searches in a backlog run (FRG-SRCH-009). Clamped UP to a "
            "documented 30 s floor so indexer API limits are respected — a "
            "smaller value is raised to the floor, never honored as-is."
        ),
    )
    comicvine_api_key: SecretStr = Field(
        default=SecretStr(""),
        description="ComicVine API key (secret; empty by default, supply at runtime).",
    )
    comicvine_base_url: str = Field(
        default="https://comicvine.gamespot.com/api",
        description=(
            "Base URL of the ComicVine API. Defaults to the real service and is "
            "only overridden to point the metadata client at a fixture server "
            "(the end-to-end harness, FRG-PROC-010). Every request carries the "
            "ComicVine API key, so the scheme MUST be https unless "
            "comicvine_insecure_base explicitly opts in (test fixtures only) — "
            "a plaintext override would exfiltrate the key to whatever host "
            "this names. The outbound egress policy (FRG-SEC-001) additionally "
            "applies to whatever host this resolves to."
        ),
    )
    comicvine_insecure_base: bool = Field(
        default=False,
        description=(
            "Permit a plain-http comicvine_base_url. A TEST AFFORDANCE for the "
            "e2e fixture network only — never set in production; the API key "
            "rides every request."
        ),
    )
    comicvine_min_interval_seconds: float = Field(
        default=2.0,
        gt=0,
        description=(
            "Minimum seconds between ANY two ComicVine requests (the shared "
            "process-global rate limiter, covers included). Politeness budget; "
            "clamped up to a documented safety floor if set lower."
        ),
    )
    comicvine_page_size: int = Field(
        default=100,
        ge=1,
        le=100,
        description=(
            "ComicVine list page size for the offset walk. ComicVine caps this "
            "at 100 results per page."
        ),
    )
    comicvine_max_pages: int = Field(
        default=200,
        ge=1,
        description=(
            "Hard cap on pages walked for one ComicVine list endpoint; bounds "
            "the pagination loop so it can never run unbounded."
        ),
    )
    comicvine_search_result_cap: int = Field(
        default=1000,
        ge=1,
        description=(
            "Maximum ComicVine series-search candidates returned; results "
            "beyond this are truncated with a visible warning."
        ),
    )
    credits_fetch_per_refresh: int = Field(
        default=25,
        description=(
            "Maximum per-issue ComicVine credit detail fetches a single series "
            "refresh performs (FRG-CRTR-001). ComicVine serves person_credits "
            "ONLY on the issue detail endpoint (the list endpoint returns null), "
            "so every credit-needing issue costs one extra rate-gated request. "
            "At the default comicvine_min_interval_seconds of 2 s that is ~2 s "
            "per issue — the default 25 adds up to ~50 s to a refresh. The "
            "newest credit-needing issues are fetched first; the tail backfills "
            "across subsequent scheduled/force refreshes. Clamped to the safe "
            "range 1..200 with a warning if set outside it."
        ),
    )
    comicvine_hourly_path_budget: int = Field(
        default=150,
        description=(
            "Soft per-path hourly ComicVine request ceiling (FRG-META-016). "
            "ComicVine limits an API key to 200 requests/hour PER resource path "
            "(/volume, /issues, /issue, /volumes, /person, ...) on top of the "
            "velocity spacing, and request spacing alone can exhaust that in "
            "minutes. When a path reaches this ceiling over a rolling hour the "
            "client refuses further requests on that path locally (a typed, "
            "logged deferral with a resume time; NOT a server-visible rate-limit "
            "signal) and resumes automatically as the window rolls. The default "
            "150 leaves ~25% headroom under ComicVine's limit for other tools "
            "sharing the key and for clock skew. Clamped to the documented "
            "10..200 range with a warning if set outside it — never above 200."
        ),
    )
    comicvine_refresh_max_skip_days: int = Field(
        default=7,
        description=(
            "Maximum age (days) of the last COMPLETE issue walk for which a "
            "series refresh may short-circuit (FRG-META-017). When ComicVine's "
            "volume ``date_last_updated`` is unchanged since the last complete "
            "walk AND that walk is newer than this bound, the refresh skips the "
            "issue pagination walk entirely (ComicVine's own caching guidance). "
            "The bound guarantees a full walk runs at least this often as a "
            "correctness backstop even when the volume stamp never changes. "
            "Clamped up to a floor of 1 day."
        ),
    )
    comicvine_ignored_publishers: str = Field(
        default="",
        description=(
            "Comma-separated ComicVine publisher names excluded from series "
            "search (e.g. variant-cover/reprint-only imprints). Case-insensitive."
        ),
    )
    comicvine_image_hosts: str = Field(
        default="comicvine.gamespot.com,comicvine1.cbsistatic.com,static.comicvine.com",
        description=(
            "Comma-separated allowlist of hostnames the cover fetcher may "
            "download images from. Not hardcoded so operators can adjust it "
            "when ComicVine's image CDN changes."
        ),
    )
    # Per-provider credentials (DogNZB/NZB.su/SABnzbd API keys) live in per-row
    # provider settings JSON entered through the Settings UI (FRG-IDX-001 /
    # FRG-DL-002), NOT as global config-file fields. The vestigial global
    # dognzb_api_key/nzbsu_api_key/sabnzbd_api_key SecretStr fields (zero
    # consumers) were removed under FRG-DEP-003 (m2-first-run-defaults): the
    # only global secret placeholder in the documented config is
    # comicvine_api_key. extra="ignore" plus load_settings' unknown-key pop keep
    # an existing config.yaml carrying the stale keys loading (logged warning).
    track_downloads_interval_seconds: int = Field(
        default=60,
        ge=60,
        description=(
            "How often the scheduled TrackDownloadsCommand polls every enabled "
            "download client and advances the tracked-download state machine "
            "(FRG-DL-007). Minimum 60 s (the download pool is serialized)."
        ),
    )
    auto_redownload_failed: bool = Field(
        default=True,
        description=(
            "When a tracked download fails, immediately enqueue a fresh search "
            "for the affected issues so the blocklist + decision engine select a "
            "different release (FRG-DL-013, the self-healing loop). On by default."
        ),
    )
    pull_enabled: bool = Field(
        default=True,
        description=(
            "Enable the weekly-pull external source fetch (FRG-PULL-002). ON by "
            "default (owner decision 2026-07-11) so the Calendar shows the week's "
            "releases out of the box; set false to opt out — the weekly view "
            "(FRG-PULL-001) still works from local library metadata alone, the "
            "scheduled pull-refresh task no-ops cleanly, and no third-party "
            "traffic is issued. A source outage degrades health, never the view."
        ),
    )
    pull_source_url: str = Field(
        default="https://walksoftly.itsaninja.party/newcomics.php",
        description=(
            "URL of the external weekly-pull JSON source (FRG-PULL-002): the "
            "walksoftly / League-of-Comic-Geeks-derived API. Fetched over the "
            "hardened 'external' egress profile (FRG-SEC-001) — a loopback/private/"
            "link-local host is refused per-hop and surfaced as a degraded source, "
            "never used to reach an internal host. Only fetched when pull_enabled "
            "is true; an empty value disables the fetch."
        ),
    )
    pull_refresh_interval_seconds: int = Field(
        default=14400,
        ge=1,
        description=(
            "How often the scheduled pull-refresh task fetches the current + "
            "previous release weeks, stores them, matches to the library, and "
            "triggers refresh-series for matched-but-missing issues (FRG-PULL-006). "
            "Default 4 hours (14400 s); clamped UP to a documented 1 hour (3600 s) "
            "floor at task registration to protect the unofficial third-party "
            "source — a smaller value is raised to the floor, not rejected. A "
            "manual force-run (POST /api/v1/system/task/pull-refresh) bypasses the "
            "interval gate and runs immediately."
        ),
    )
    source_sync_interval_seconds: int = Field(
        default=86400,
        ge=1,
        description=(
            "How often the scheduled store-source sync task polls connected "
            "sources (e.g. Humble Bundle) for new entitlements (FRG-SRC-003). "
            "Default daily (86400 s); clamped UP to a documented 1 hour (3600 s) "
            "floor at task registration to stay polite to the store API "
            "(FRG-NFR-005). A manual 'Sync now' (POST /api/v1/sources/{id}/sync) "
            "runs immediately regardless of this interval."
        ),
    )
    source_min_request_interval_seconds: float = Field(
        default=2.0,
        ge=0.1,
        description=(
            "Minimum seconds between two consecutive HTTP requests to one store "
            "source, enforced across the order-list → order-detail fan "
            "(FRG-NFR-005). Default 2 s; floored at 0.1 s."
        ),
    )
    humble_base_url: str = Field(
        default="https://www.humblebundle.com",
        description=(
            "Base URL of the Humble Bundle order API (FRG-SRC-002). Defaults to "
            "the real service and is only overridden to point the store client at "
            "a fixture server (the end-to-end harness, FRG-PROC-010). Every "
            "request carries the operator's session cookie, so the scheme MUST be "
            "https unless humble_insecure_base explicitly opts in (test fixtures "
            "only) — a plaintext override would exfiltrate the session cookie to "
            "whatever host this names. The outbound egress policy (FRG-SEC-001) "
            "additionally applies to whatever host this resolves to."
        ),
    )
    humble_insecure_base: bool = Field(
        default=False,
        description=(
            "Permit a plain-http humble_base_url. A TEST AFFORDANCE for the e2e "
            "fixture network only — never set in production; the session cookie "
            "rides every request."
        ),
    )
    opds_base_path: str = Field(
        default="/opds",
        description=(
            "Base URL path the OPDS 1.2 catalog is mounted at (FRG-OPDS-001). "
            "Must start with '/'; a trailing slash is stripped. All in-feed "
            "links are built relative to this base."
        ),
    )
    opds_page_size: int = Field(
        default=50,
        ge=1,
        description=(
            "Default number of entries per OPDS feed page (FRG-OPDS-006) when "
            "the client does not request a page size."
        ),
    )
    opds_page_size_cap: int = Field(
        default=100,
        ge=1,
        description=(
            "Hard upper bound on the OPDS feed page size (FRG-OPDS-006): a "
            "client requesting a larger page is clamped to this value, never "
            "served an unbounded page."
        ),
    )
    opds_pse_max_members: int = Field(
        default=5000,
        ge=1,
        description=(
            "OPDS Page-Streaming (FRG-OPDS-012): maximum number of members an "
            "archive may declare before it is refused for page/cover extraction "
            "— a member-count cap on the central directory, checked before any "
            "decompression. Folded into a per-request ArchiveLimits override."
        ),
    )
    opds_pse_max_page_bytes: int = Field(
        default=64 * 1024 * 1024,
        ge=1,
        description=(
            "OPDS Page-Streaming (FRG-OPDS-012): maximum DECLARED decompressed "
            "size (bytes) of a single archive page; a member declaring more is "
            "refused before it is read (zip-bomb defense). Default 64 MiB."
        ),
    )
    opds_pse_max_pixels: int = Field(
        default=64_000_000,
        ge=1,
        description=(
            "OPDS Page-Streaming (FRG-OPDS-012): maximum decoded pixel count "
            "(width*height) of a page image; an image whose header declares more "
            "is refused before its pixels are loaded (decompression-bomb guard). "
            "Default 64 megapixels."
        ),
    )
    opds_pse_request_timeout_seconds: float = Field(
        default=20.0,
        gt=0,
        description=(
            "OPDS Page-Streaming (FRG-OPDS-012): per-request wall-clock budget "
            "(seconds) for a page/cover decode+resize; an over-budget decode is "
            "abandoned with a bounded 5xx rather than spinning unbounded."
        ),
    )
    opds_pse_max_width: int = Field(
        default=2048,
        ge=1,
        description=(
            "OPDS Page-Streaming (FRG-OPDS-008): hard ceiling (pixels) on the "
            "client-requested page ``width``; a larger request is clamped to "
            "this value. Pages are never upscaled."
        ),
    )

    rename_enabled: bool = Field(
        default=False,
        description=(
            "Rename imported files to the file naming template. Off by default "
            "(FRG-PP-020): a fresh install adopts an existing library without "
            "touching any file name or path; renaming is opt-in. When off, an "
            "imported file keeps its original name (FRG-PP-012)."
        ),
    )
    file_naming_template: str = Field(
        default=DEFAULT_FILE_NAMING_TEMPLATE,
        description=(
            "Token template for imported/renamed file names (FRG-PP-009), applied "
            "only when rename_enabled is on. Tokens like {Series Title} "
            "{Issue Number:000} ({Year}) are substituted; the template must "
            "round-trip a probe identity back through the parser so a renamed "
            "file stays reconcilable to its issue. The shipped default carries no "
            "internal-id tag (FRG-PP-020); add {CvIssueId} to opt into a durable "
            "identity tag that survives a database reinstall."
        ),
    )
    folder_naming_template: str = Field(
        default=DEFAULT_FOLDER_TEMPLATE,
        description=(
            "Token template for the series folder name (FRG-PP-010), e.g. "
            "{Series Title} ({Year})."
        ),
    )
    replace_illegal_characters: bool = Field(
        default=True,
        description=(
            "Replace filesystem-illegal characters in rendered file names with a "
            "space instead of leaving them (FRG-PP-009)."
        ),
    )
    import_transfer_mode: str = Field(
        default="move",
        description=(
            "How a completed download is placed into the library: move, copy, or "
            "hardlink (FRG-PP-007). 'move' is the correct default for a file "
            "arriving in a download directory."
        ),
    )
    library_import_mode: str = Field(
        default="in_place",
        description=(
            "How an existing-library import treats files already under the library "
            "root: in_place (safe default — never re-move) or move. Honored by the "
            "existing-library import path (defined here, wired in a later change)."
        ),
    )
    library_import_proposal_cap: int = Field(
        default=50,
        ge=1,
        description=(
            "Maximum ComicVine match proposals ONE library-import scan run "
            "performs (each proposal is a live, politeness-gated search). "
            "Groups beyond the cap stage without a proposed match — visibly, "
            "never silently — and pick one up on a later re-scan."
        ),
    )
    library_import_similarity_floor: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum name similarity (0.0-1.0) the best ComicVine search "
            "candidate must reach for a library-import scan to attach it as a "
            "group's proposed match; below the floor the group stages as "
            "no-match for manual resolution (never guessed)."
        ),
    )
    recycle_bin_path: str = Field(
        default="",
        description=(
            "Directory that upgrade-replaced and user-deleted library files are "
            "moved to instead of being permanently deleted (FRG-PP-013). Empty "
            "means permanently delete. Must be a writable directory when set."
        ),
    )
    recycle_bin_retention_days: int = Field(
        default=0,
        ge=0,
        description=(
            "Days recycle-bin entries are kept before housekeeping permanently "
            "removes them (FRG-PP-013). 0 keeps them forever."
        ),
    )
    duplicate_constraint: str = Field(
        default="larger-size",
        description=(
            "How a same-rung duplicate — an incoming file for an issue whose "
            "existing file ties on the format-profile ladder — is resolved "
            "(FRG-PP-014): larger-size (the incoming file must be strictly larger "
            "to replace the existing one) or preferred-format (the profile's "
            "format preference decides; a true tie keeps the existing file). "
            "Fixed-release markers like (f1)/(f2) always win regardless of this "
            "constraint. Profile-order upgrades are unaffected."
        ),
    )
    duplicate_dump_path: str = Field(
        default="",
        description=(
            "Directory the losing file of a duplicate resolution is moved to, in "
            "dated subfolders, instead of being deleted or recycled (FRG-PP-014). "
            "Empty means the normal replaced-file handling (recycle bin, or "
            "permanent delete) applies. Not a recycle bin: retention pruning "
            "never removes anything under it."
        ),
    )
    comicinfo_tag_on_import: bool = Field(
        default=False,
        description=(
            "Write a ComicInfo.xml tag into cbz archives on import, built from the "
            "matched ComicVine issue record (FRG-PP-017). Off by default; the "
            "embedded-metadata READ during import (FRG-IMP-024) is always active "
            "and is not gated by this toggle."
        ),
    )
    config_backup_retention: int = Field(
        default=3,
        ge=1,
        description=(
            "Number of pre-config-migration backups retained under backups/; the "
            "oldest beyond this count are pruned (FRG-DEP-004)."
        ),
    )
    config_schema_version: int = Field(
        default=CURRENT_CONFIG_VERSION,
        ge=0,
        description=(
            "Schema version stamped into this config file. Managed automatically: "
            "an older file is migrated forward at startup, a newer one refuses to "
            "start (FRG-DEP-004). Do not edit by hand."
        ),
    )

    # --- Listener inbound resource limits (FRG-NFR-014) ---
    # Availability controls on the inbound HTTP/WebSocket listener: generous,
    # documented defaults so nothing in the single-admin happy path is ever
    # refused; the limits bite only under the abusive request shapes RISK-021
    # describes. The HTTP limits are enforced by the api/limits.py middleware
    # (HTTP scope only — never the long-lived WebSocket); the ws_* limits are
    # consumed by the WebSocket router/broadcaster.
    listener_max_body_bytes: int = Field(
        default=8 * 1024 * 1024,
        ge=64 * 1024,
        description=(
            "Maximum inbound HTTP request body size in bytes (default 8 MiB, "
            "floor 64 KiB). foragerr has no inbound file-upload endpoint, so "
            "this is generous headroom over the small JSON bodies the API "
            "accepts. A request whose body exceeds the cap — including one with "
            "an omitted or lying Content-Length that drips unboundedly — is "
            "rejected with 413 at the cap, streamed and aborted rather than "
            "buffered whole (FRG-NFR-014)."
        ),
    )
    listener_max_header_bytes: int = Field(
        default=16 * 1024,
        ge=1024,
        description=(
            "Maximum total inbound HTTP header size in bytes (default 16 KiB, "
            "floor 1 KiB). A request whose combined headers exceed the cap is "
            "rejected with a bounded 431 before a handler runs (FRG-NFR-014)."
        ),
    )
    listener_request_timeout_seconds: int = Field(
        default=30,
        description=(
            "Maximum seconds an inbound HTTP request may run before the "
            "listener aborts it with a 503 and releases the worker (FRG-NFR-014). "
            "Endpoints return quickly (heavy work is queued as scheduler "
            "commands), so 30 s is comfortable headroom. Enforced on the HTTP "
            "scope only — the long-lived WebSocket is never subject to it. "
            f"Clamped to the safe range {_REQ_TIMEOUT_LO}..{_REQ_TIMEOUT_HI} "
            "with a warning if set outside it."
        ),
    )
    listener_rate_max_requests: int = Field(
        default=240,
        ge=0,
        description=(
            "Per-client inbound request cap per listener_rate_window_seconds "
            "(default 240). A single peer address exceeding it in the window is "
            "rejected with 429 + Retry-After (FRG-NFR-014). This is a "
            "single-user-tailnet DoS safety valve, not throttling or access "
            "control; the generous default keeps it clear of the normal admin. "
            "Set to 0 to disable per-client rate limiting entirely."
        ),
    )
    listener_rate_window_seconds: int = Field(
        default=1,
        description=(
            "Sliding-window length in seconds for the per-client request rate "
            "cap (default 1). "
            f"Clamped to the safe range {_RATE_WIN_LO}..{_RATE_WIN_HI} with a "
            "warning if set outside it (FRG-NFR-014)."
        ),
    )
    ws_max_connections: int = Field(
        default=32,
        ge=1,
        description=(
            "Maximum number of concurrent WebSocket connections (default 32, "
            "floor 1). A connection attempted at or above the cap is refused "
            "cleanly at the handshake without disturbing existing connections "
            "(FRG-NFR-014)."
        ),
    )
    ws_max_inbound_bytes: int = Field(
        default=4096,
        ge=64,
        description=(
            "Maximum size in bytes of a single inbound WebSocket frame (default "
            "4 KiB, floor 64). The WebSocket is server-push; inbound frames are "
            "only a disconnect detector, so an over-size inbound frame closes "
            "that socket cleanly rather than buffering unbounded memory "
            "(FRG-NFR-014)."
        ),
    )
    ws_max_inbound_messages_per_second: int = Field(
        default=10,
        ge=1,
        description=(
            "Maximum sustained inbound WebSocket frames per second per socket "
            "(default 10). A client flooding inbound frames beyond this rate has "
            "that socket closed cleanly (FRG-NFR-014)."
        ),
    )

    @classmethod
    def settings_customise_sources(  # env vars override init kwargs (= file values)
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (env_settings, init_settings, dotenv_settings, file_secret_settings)

    @field_validator("opds_base_path")
    @classmethod
    def _valid_opds_base_path(cls, value: str) -> str:
        """Normalize the OPDS mount path: exactly one leading slash, no
        trailing slash (so ``f"{base}/series"`` never doubles a separator), and
        reject values that collide with a core mount (``/``, ``/api``,
        ``/health``) — those would silently break the SPA or the API."""
        path = value.strip()
        if not path.startswith("/"):
            raise ValueError("must start with '/'")
        path = "/" + path.strip("/")
        if path == "/":
            raise ValueError("must not be the root path '/' (it hosts the SPA)")
        for reserved in _OPDS_RESERVED_PATHS:
            if path == reserved or path.startswith(reserved + "/"):
                raise ValueError(
                    f"must not collide with the reserved mount {reserved!r}"
                )
        return path

    @field_validator("comicvine_base_url")
    @classmethod
    def _comicvine_base_shape(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError(
                "comicvine_base_url must be an absolute http(s) URL"
            )
        return value.rstrip("/")

    @model_validator(mode="after")
    def _comicvine_base_requires_tls(self):
        if self.comicvine_base_url.startswith("http://") and not self.comicvine_insecure_base:
            raise ValueError(
                "comicvine_base_url uses plain http, which would send the "
                "ComicVine API key unencrypted; use https, or set "
                "comicvine_insecure_base=true if this is a test fixture"
            )
        return self

    @field_validator("humble_base_url")
    @classmethod
    def _humble_base_shape(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError(
                "humble_base_url must be an absolute http(s) URL"
            )
        return value.rstrip("/")

    @model_validator(mode="after")
    def _humble_base_requires_tls(self):
        if self.humble_base_url.startswith("http://") and not self.humble_insecure_base:
            raise ValueError(
                "humble_base_url uses plain http, which would send the "
                "Humble session cookie unencrypted; use https, or set "
                "humble_insecure_base=true if this is a test fixture"
            )
        return self

    @field_validator("credits_fetch_per_refresh")
    @classmethod
    def _clamp_credits_fetch_per_refresh(cls, value: int) -> int:
        """Clamp the per-refresh credit-fetch bound to a documented 1..200 range
        with a warning, rather than fail startup (FRG-CRTR-001, decision 3). A
        value below 1 would stall the credit backfill entirely; above 200 would
        let one refresh spend many minutes under the 2 s gate."""
        clamped = min(max(value, 1), 200)
        if clamped != value:
            logger.warning(
                "config: credits_fetch_per_refresh=%s is outside the safe range "
                "1..200; clamped to %s",
                value,
                clamped,
            )
        return clamped

    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, value: str) -> str:
        upper = value.strip().upper()
        if upper not in _LOG_LEVELS:
            raise ValueError(f"must be one of {', '.join(_LOG_LEVELS)}")
        return upper

    @field_validator("config_dir")
    @classmethod
    def _config_dir_usable(cls, value: Path) -> Path:
        value = value.expanduser()
        if value.exists():
            if not value.is_dir():
                raise ValueError(f"path exists but is not a directory: {value}")
            if not os.access(value, os.W_OK):
                raise ValueError(f"directory is not writable: {value}")
        return value

    @field_validator("file_naming_template", "folder_naming_template")
    @classmethod
    def _template_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("naming template must not be empty")
        return value

    @field_validator("file_naming_template")
    @classmethod
    def _file_template_round_trips_check(cls, value: str) -> str:
        if not _file_template_round_trips(value):
            raise ValueError(
                "file naming template must render a name that round-trips back to "
                "the same series and issue, and that stays distinct across issue "
                "numbers — keep {Series Title} and {Issue Number}"
            )
        return value

    @field_validator("import_transfer_mode")
    @classmethod
    def _valid_transfer_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _TRANSFER_MODES:
            raise ValueError(f"must be one of {', '.join(_TRANSFER_MODES)}")
        return normalized

    @field_validator("library_import_mode")
    @classmethod
    def _valid_library_import_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _LIBRARY_IMPORT_MODES:
            raise ValueError(f"must be one of {', '.join(_LIBRARY_IMPORT_MODES)}")
        return normalized

    @field_validator("duplicate_constraint")
    @classmethod
    def _valid_duplicate_constraint(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _DUPLICATE_CONSTRAINTS:
            raise ValueError(f"must be one of {', '.join(_DUPLICATE_CONSTRAINTS)}")
        return normalized

    @field_validator("recycle_bin_path", "duplicate_dump_path")
    @classmethod
    def _recycle_bin_usable(cls, value: str) -> str:
        """Empty is allowed (permanent delete / normal disposal); a set path must
        be a writable, confinement-safe directory — same fail-fast posture as
        ``config_dir``. Shared by the recycle bin (FRG-PP-013) and the
        duplicate-dump folder (FRG-PP-014)."""
        text = value.strip()
        if not text:
            return ""
        path = Path(text).expanduser()
        if path.exists():
            if not path.is_dir():
                raise ValueError(f"path exists but is not a directory: {path}")
            if not os.access(path, os.W_OK):
                raise ValueError(f"directory is not writable: {path}")
        else:
            parent = path.parent
            if not parent.exists() or not os.access(parent, os.W_OK):
                raise ValueError(
                    f"path {path} does not exist and its parent is not a "
                    "writable directory"
                )
        return str(path)

    @model_validator(mode="after")
    def _clamp_intervals(self) -> "Settings":
        for name, (floor, ceiling) in INTERVAL_RANGES.items():
            supplied = getattr(self, name)
            clamped = min(max(supplied, floor), ceiling)
            if clamped != supplied:
                logger.warning(
                    "config: %s=%s is outside the safe range %s..%s; clamped to %s",
                    name,
                    supplied,
                    floor,
                    ceiling,
                    clamped,
                )
                setattr(self, name, clamped)
        return self

    def opds_pse_archive_limits(self) -> ArchiveLimits:
        """Per-request archive-safety limits for the OPDS-PSE *listing* surface.

        Folds ``opds_pse_max_members`` into an :class:`ArchiveLimits` override the
        stream and cover endpoints pass to ``list_image_members`` (FRG-OPDS-012),
        tightening only the member-count cap for the untrusted OPDS listing path.

        Crucially, ``max_member_bytes`` stays at the shared DEFAULT import cap —
        NOT the tight ``opds_pse_max_page_bytes``. Listability must match what the
        import producer decided (which counts under the default import limits): if
        this used the tight per-page cap, a CBZ with one page larger than
        ``opds_pse_max_page_bytes`` would be listed (and counted) at import yet
        return ``None`` from ``list_image_members`` at stream time, 404-ing the
        WHOLE archive. The tight per-page byte cap is instead enforced ONLY at
        read time, in ``read_image_member(..., max_bytes=opds_pse_max_page_bytes)``,
        so a single over-64-MiB page returns a bounded per-page 502 while every
        other page still streams. Net: an archive is streamable iff it passed
        import. Total-size and nesting stay at the shared defaults.
        """
        return ArchiveLimits(
            max_members=self.opds_pse_max_members,
            max_member_bytes=DEFAULT_ARCHIVE_LIMITS.max_member_bytes,
        )

    def auth_extra_origins(self) -> set[str]:
        """Configured extra allowed Origins (CSRF + WS handshake, FRG-SEC-005)."""
        return {
            origin.strip()
            for origin in self.auth_origin_allowlist.split(",")
            if origin.strip()
        }

    def secret_fields(self) -> dict[str, SecretStr]:
        """All secret-typed settings by field name."""
        return {
            name: value
            for name, value in ((n, getattr(self, n)) for n in type(self).model_fields)
            if isinstance(value, SecretStr)
        }


def render_documented_config(values: dict[str, Any] | None = None) -> str:
    """Render a fully documented ``config.yaml`` body (FRG-DEP-003).

    Every setting is emitted with its explanatory comment (from the ``Field``
    description) and its built-in default; secrets and the environment-only
    ``config_dir`` are commented placeholders. This is the ONE renderer used for
    both the first-run write (``values=None`` ⇒ pure defaults) AND every rewrite
    (migration, config-resource ``PUT``): passing the CURRENT ``values`` emits the
    same documented shape carrying live values, so no rewrite ever strips the
    documentation the first-run file promised. Any key not in the model (an
    operator/unknown key) is preserved verbatim at the end rather than dropped.
    """
    provided = values or {}
    lines = [
        "# foragerr configuration",
        "#",
        "# Every setting is listed with its built-in default. A FORAGERR_<NAME>",
        "# environment variable always overrides the value in this file.",
        "# Secrets are commented out: supply them via environment variables or",
        "# by uncommenting the line — they have no built-in default.",
        "",
    ]
    for name, field in Settings.model_fields.items():
        for text in (field.description or name).splitlines():
            lines.append(f"# {text}")
        if name == "config_dir":
            lines.append("# (not read from this file — environment only)")
            lines.append(f"# default: {DEFAULT_CONFIG_DIR}")
            lines.append(f"#config_dir: {DEFAULT_CONFIG_DIR}")
            lines.append("")
            continue
        if name in _ENV_ONLY_SECRETS:
            # Environment-only secrets: never emit a settable/placeholder line so
            # the value can never be captured into the config file.
            lines.append(
                f"# (not read from this file — set the FORAGERR_{name.upper()} "
                "environment variable only)"
            )
            lines.append("")
            continue
        default = field.default
        if isinstance(default, SecretStr):
            supplied = provided.get(name)
            lines.append("# default: (empty)")
            if supplied:  # operator set the secret in the file — preserve it
                lines.append(yaml.safe_dump({name: supplied}, sort_keys=False).strip())
            else:
                lines.append(f'#{name}: ""')
        else:
            current = provided.get(name, default)
            lines.append(f"# default: {default}")
            lines.append(yaml.safe_dump({name: current}, sort_keys=False).strip())
        lines.append("")
    extras = {
        key: val
        for key, val in provided.items()
        if key not in Settings.model_fields and key != "config_dir"
    }
    if extras:
        lines.append("# keys not recognized by this build (preserved verbatim):")
        lines.append(yaml.safe_dump(extras, sort_keys=False).strip())
        lines.append("")
    return "\n".join(lines) + "\n"


def generate_default_config(path: Path) -> None:
    """Write a first-run ``config.yaml`` (FRG-DEP-003): the documented defaults,
    written atomically."""
    atomic_write_text(path, render_documented_config())


def _format_validation_error(exc: ValidationError) -> str:
    parts = [f"invalid configuration — {exc.error_count()} error(s):"]
    for err in exc.errors():
        loc = ".".join(str(piece) for piece in err["loc"]) or "<config>"
        parts.append(f"  - {loc}: {err['msg']} (got: {err.get('input')!r})")
    return "\n".join(parts)


def load_settings() -> Settings:
    """Resolve the config dir, generate/read ``config.yaml``, apply env
    overrides, validate everything in one pass, register secrets.

    Raises :class:`ConfigError` with field-precise messages on any failure.
    """
    config_dir = resolve_config_dir()
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigError(
            f"config_dir: cannot create config directory {config_dir}: {exc}"
        ) from exc

    config_file = config_dir / CONFIG_FILENAME
    file_values: dict[str, Any] = {}
    if config_file.exists():
        try:
            loaded = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"{config_file}: invalid YAML: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ConfigError(f"{config_file}: top level must be a key/value mapping")
        # Forward-migrate the stamped config before validating (FRG-DEP-004). A
        # newer-than-supported stamp refuses startup with the file untouched.
        retention = loaded.get("config_backup_retention", 3)
        try:
            retention = int(retention)
        except (TypeError, ValueError):
            retention = 3
        try:
            file_values = migrate_config(
                config_file,
                loaded,
                config_dir,
                retention=retention,
                render=render_documented_config,
            )
        except ConfigSchemaVersionError as exc:
            raise ConfigError(str(exc)) from exc
        except OSError as exc:
            # The forward migration backs up + rewrites the file; an unwritable
            # config directory surfaces here as an OSError. Report it in the same
            # field-precise shape the config_dir writability check uses.
            raise ConfigError(
                f"config_dir: config directory is not writable, cannot migrate "
                f"{config_file}: {exc}"
            ) from exc
    else:
        try:
            generate_default_config(config_file)
        except OSError as exc:
            raise ConfigError(f"config_dir: cannot write {config_file}: {exc}") from exc

    file_values.pop("config_dir", None)  # environment-only setting
    unknown = sorted(set(file_values) - set(Settings.model_fields))
    if unknown:
        logger.warning("config: ignoring unknown key(s) in %s: %s",
                       CONFIG_FILENAME, ", ".join(unknown))
        for key in unknown:
            file_values.pop(key)

    file_values.pop("secret_key", None)  # environment-only (never read from file)
    # Bootstrap credentials are environment-only too (never persisted to the
    # config file — the password is stored only as a scrypt hash, FRG-AUTH-003).
    file_values.pop("admin_password", None)
    file_values.pop("opds_password", None)
    try:
        settings = Settings(config_dir=config_dir, **file_values)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc)) from exc

    # Mandatory at-rest encryption passphrase (FRG-AUTH-011): refuse to start
    # without it, BEFORE any migration or data access, so a keyless boot changes
    # nothing on the database. The message names the variable and the fix.
    ensure_secret_key_present(settings)

    # Mandatory login bootstrap (FRG-AUTH-002): when no principal exists yet the
    # admin env pair is required — refuse to start without it, ordered directly
    # after the keystore gate and before any migration or data write. Lazy
    # import avoids a config <-> auth import cycle.
    from foragerr.auth.bootstrap import ensure_admin_bootstrap_present

    ensure_admin_bootstrap_present(settings)

    # Redaction registry hook (FRG-NFR-008): the filter learns every secret
    # value at config-load time — including the FORAGERR_SECRET_KEY passphrase.
    for secret in settings.secret_fields().values():
        register_secret(secret.get_secret_value())

    return settings
