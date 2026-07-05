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

from foragerr.logging import register_secret

logger = _stdlog.getLogger("foragerr.config")

CONFIG_DIR_ENV = "FORAGERR_CONFIG_DIR"
DEFAULT_CONFIG_DIR = Path("/config")
CONFIG_FILENAME = "config.yaml"

_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

#: Documented safe ranges for interval settings: name -> (floor, ceiling).
#: Out-of-range supplied values are clamped with a warning (FRG-NFR-009).
INTERVAL_RANGES: dict[str, tuple[int, int]] = {
    "scheduler_tick_seconds": (5, 60),
    "shutdown_grace_seconds": (1, 29),
}

#: Range fragments derived from INTERVAL_RANGES so the generated config.yaml
#: comments (built from Field descriptions) can never drift from the bounds
#: actually enforced by ``_clamp_intervals``.
_TICK_LO, _TICK_HI = INTERVAL_RANGES["scheduler_tick_seconds"]
_GRACE_LO, _GRACE_HI = INTERVAL_RANGES["shutdown_grace_seconds"]


class ConfigError(Exception):
    """Effective configuration is invalid — startup must fail (FRG-NFR-009)."""


def resolve_config_dir() -> Path:
    """The directory holding all persistent state (FRG-DEP-002)."""
    return Path(os.environ.get(CONFIG_DIR_ENV, str(DEFAULT_CONFIG_DIR))).expanduser()


class Settings(BaseSettings):
    """Effective foragerr configuration (env > config.yaml > defaults)."""

    model_config = SettingsConfigDict(env_prefix="FORAGERR_", extra="ignore")

    config_dir: Path = Field(
        default=DEFAULT_CONFIG_DIR,
        description=(
            "Directory holding ALL persistent state: database, this config "
            "file, logs, backups. Set via the FORAGERR_CONFIG_DIR environment "
            "variable (never read from this file)."
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
    comicvine_api_key: SecretStr = Field(
        default=SecretStr(""),
        description="ComicVine API key (secret; empty by default, supply at runtime).",
    )
    dognzb_api_key: SecretStr = Field(
        default=SecretStr(""),
        description="DogNZB indexer API key (secret; empty by default, supply at runtime).",
    )
    nzbsu_api_key: SecretStr = Field(
        default=SecretStr(""),
        description="NZB.su indexer API key (secret; empty by default, supply at runtime).",
    )
    sabnzbd_api_key: SecretStr = Field(
        default=SecretStr(""),
        description="SABnzbd API key (secret; empty by default, supply at runtime).",
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

    def secret_fields(self) -> dict[str, SecretStr]:
        """All secret-typed settings by field name."""
        return {
            name: value
            for name, value in ((n, getattr(self, n)) for n in type(self).model_fields)
            if isinstance(value, SecretStr)
        }


def generate_default_config(path: Path) -> None:
    """Write a first-run ``config.yaml``: every setting, its default, and an
    explanatory comment; secrets only as commented placeholders (FRG-DEP-003)."""
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
        default = field.default
        if isinstance(default, SecretStr):
            lines.append("# default: (empty)")
            lines.append(f'#{name}: ""')
        else:
            lines.append(f"# default: {default}")
            lines.append(yaml.safe_dump({name: default}, sort_keys=False).strip())
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
        file_values = loaded
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

    try:
        settings = Settings(config_dir=config_dir, **file_values)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc)) from exc

    # Redaction registry hook (FRG-NFR-008): the filter learns every secret
    # value at config-load time.
    for secret in settings.secret_fields().values():
        register_secret(secret.get_secret_value())

    return settings
