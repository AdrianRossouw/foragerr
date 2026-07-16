"""Typed config resource endpoints (FRG-API-013).

GET/PUT singletons for the naming and media-management settings the settings
screens read and write, so all config changes flow through the documented API
rather than ad-hoc form posts. Each ``PUT`` validates the whole effective config
(via the :class:`~foragerr.config.Settings` model), persists the change into
``config.yaml``, and re-loads ``app.state.settings`` so a subsequent GET — and the
rename preview — see the new values. A field-precise 4xx flows through the uniform
error shape (``{"message", "errors":[{"field","message"}]}``) with each offending
setting named under a ``settings.`` prefix (the shape the frontend ``mapApiError``
strips). No secret-typed field appears in these resources — secrets remain DEP/AUTH
surface.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from foragerr.api.errors import ApiError, error_body
from foragerr.config import CONFIG_FILENAME, Settings, render_documented_config
from foragerr.config_migrations import atomic_write_text
from foragerr.library.flows import comicvine_factory
from foragerr.logging import register_secret
from foragerr.metadata import ComicVineAuthError, ComicVineClient, ComicVineError
from foragerr.metadata.errors import COMICVINE_CREDENTIAL_MESSAGE
from foragerr.naming import (
    DEFAULT_FILE_TEMPLATE,
    DEFAULT_FOLDER_TEMPLATE,
    _TOKEN_ALIASES,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["config"])

#: The environment variable that supplies the ComicVine key and, per pydantic
#: precedence, outranks the config-file value (``config.py`` env-over-file
#: source ordering). The credential resource reads it DIRECTLY (not through the
#: collapsed ``Settings`` object) — the one place in the app that must tell an
#: env-supplied key from a file-supplied one, because the effective ``Settings``
#: object cannot say which source won.
COMICVINE_KEY_ENV_VAR = "FORAGERR_COMICVINE_API_KEY"

#: The environment variable that supplies the ignored-publishers list and, like
#: the key, outranks the config-file value. Read DIRECTLY (case-insensitive,
#: empty ignored to mirror ``env_ignore_empty``) so the resource can report
#: whether the effective value is env-managed — the collapsed ``Settings`` object
#: cannot say which source won.
COMICVINE_IGNORED_PUBLISHERS_ENV_VAR = "FORAGERR_COMICVINE_IGNORED_PUBLISHERS"

#: A neutral, cheap probe term for the connectivity test (a single-page suggest
#: search) — it exercises the effective key against ComicVine without persisting
#: anything and without depending on any particular library content.
_COMICVINE_TEST_TERM = "batman"

#: Serializes the read-modify-write-reload of ``config.yaml`` across concurrent
#: PUTs to ANY config resource, so two overlapping updates can't lost-update each
#: other (each re-reads the file the other just wrote under the lock).
_config_write_lock = asyncio.Lock()


class NamingTokens(BaseModel):
    """The shared naming-token vocabulary (FRG-API-013, FRG-UI-012).

    A read-only projection of the one canonical token table
    (:data:`foragerr.naming._TOKEN_ALIASES`) so the settings UI's live example
    preview and its ``?`` token-help popover both render from the SAME
    definition the server renders with — never a hand-maintained duplicate
    list. ``aliases`` maps every accepted (casefolded) token name to its
    canonical field key; ``defaults`` carries the default templates so the UI
    can seed / reset without hardcoding them.
    """

    aliases: dict[str, str]
    defaults: dict[str, str]


@router.get("/naming/tokens", response_model=NamingTokens)
async def get_naming_tokens() -> NamingTokens:
    """Return the shared token vocabulary the naming templates accept.

    Read-only and config-independent — the vocabulary is a property of the
    renderer, not of the stored settings — so no ``Request``/settings access is
    needed. Sourced verbatim from :data:`foragerr.naming._TOKEN_ALIASES` (which
    ``importer.renamer`` re-exports), keeping the UI and the server on one
    definition (design decision 11).
    """
    return NamingTokens(
        aliases=dict(_TOKEN_ALIASES),
        defaults={
            "file_naming_template": DEFAULT_FILE_TEMPLATE,
            "folder_naming_template": DEFAULT_FOLDER_TEMPLATE,
        },
    )


class NamingConfig(BaseModel):
    """The naming settings resource (no secret fields)."""

    rename_enabled: bool
    file_naming_template: str
    folder_naming_template: str
    replace_illegal_characters: bool

    @classmethod
    def from_settings(cls, settings: Settings) -> "NamingConfig":
        return cls(
            rename_enabled=settings.rename_enabled,
            file_naming_template=settings.file_naming_template,
            folder_naming_template=settings.folder_naming_template,
            replace_illegal_characters=settings.replace_illegal_characters,
        )


class MediaManagementConfig(BaseModel):
    """The media-management settings resource (no secret fields)."""

    import_transfer_mode: str
    library_import_mode: str
    # Library-import scan tuning (FRG-IMP-023): per-run proposal cap + the
    # plausibility floor for attaching a proposed ComicVine match.
    library_import_proposal_cap: int
    library_import_similarity_floor: float
    recycle_bin_path: str
    recycle_bin_retention_days: int
    # Same-rung duplicate handling (FRG-PP-014): constraint + optional dump root.
    duplicate_constraint: str
    duplicate_dump_path: str

    @classmethod
    def from_settings(cls, settings: Settings) -> "MediaManagementConfig":
        return cls(
            import_transfer_mode=settings.import_transfer_mode,
            library_import_mode=settings.library_import_mode,
            library_import_proposal_cap=settings.library_import_proposal_cap,
            library_import_similarity_floor=settings.library_import_similarity_floor,
            recycle_bin_path=settings.recycle_bin_path,
            recycle_bin_retention_days=settings.recycle_bin_retention_days,
            duplicate_constraint=settings.duplicate_constraint,
            duplicate_dump_path=settings.duplicate_dump_path,
        )


@router.get("/naming", response_model=NamingConfig)
async def get_naming(request: Request) -> NamingConfig:
    """Return the current typed naming values (FRG-API-013)."""
    return NamingConfig.from_settings(request.app.state.settings)


@router.put("/naming", response_model=NamingConfig)
async def put_naming(body: NamingConfig, request: Request):
    """Validate + persist naming settings, re-loading app.state.settings."""
    return await _apply(request, body.model_dump(), NamingConfig)


@router.get("/mediamanagement", response_model=MediaManagementConfig)
async def get_media_management(request: Request) -> MediaManagementConfig:
    """Return the current typed media-management values (FRG-API-013)."""
    return MediaManagementConfig.from_settings(request.app.state.settings)


@router.put("/mediamanagement", response_model=MediaManagementConfig)
async def put_media_management(body: MediaManagementConfig, request: Request):
    """Validate + persist media-management settings, re-loading app.state.settings."""
    return await _apply(request, body.model_dump(), MediaManagementConfig)


# --- ComicVine credential settings resource (FRG-API-018) -------------------


def _comicvine_source(settings: Settings) -> str:
    """Report where the effective ComicVine key comes from (never its value).

    Reads ``FORAGERR_COMICVINE_API_KEY`` from the environment DIRECTLY — the one
    place that must distinguish an env-supplied key from a file-supplied one,
    because pydantic collapses both into ``settings.comicvine_api_key`` and the
    effective object cannot say which source won (design decision 2). A non-empty
    env var ⇒ ``"environment"`` (it also outranks the file); else a non-empty
    file/effective value ⇒ ``"file"``; else ``"unset"``.

    The scan is CASE-INSENSITIVE and skips empty values to match pydantic's
    effective behavior: pydantic-settings matches env names case-insensitively,
    so a lowercase ``foragerr_comicvine_api_key`` shadows the file just as the
    exact-uppercase spelling does — an exact ``os.environ.get`` would miss it and
    report ``"file"``/``"unset"`` while the env value actually wins, producing a
    silently-ineffective editor (GET/PUT share this helper). Empty env values are
    ignored here to mirror ``env_ignore_empty=True`` on ``Settings`` (an empty
    ``FORAGERR_COMICVINE_API_KEY=""`` does NOT shadow the file key).
    """
    if any(
        k.upper() == COMICVINE_KEY_ENV_VAR and v
        for k, v in os.environ.items()
    ):
        return "environment"
    if settings.comicvine_api_key.get_secret_value():
        return "file"
    return "unset"


def _env_var_is_set(name: str) -> bool:
    """Whether ``name`` is present as a NON-EMPTY environment variable, matched
    case-insensitively — mirroring pydantic-settings' env resolution (a
    lowercase spelling shadows the file too) and ``env_ignore_empty`` (an empty
    value does not shadow). Shared by the key and ignored-publishers source
    helpers."""
    return any(k.upper() == name and v for k, v in os.environ.items())


def _ignored_publishers_source(settings: Settings) -> str:
    """Report where the effective ignored-publishers list comes from (FRG-UI-031):
    ``"env"`` (the env var wins), ``"file"`` (a value is stored in ``config.yaml``,
    including the empty string older releases rendered), else ``"default"``.
    Presence in the file — not its emptiness — distinguishes ``file`` from
    ``default``, so an upgrader who stored an empty value keeps it. Note that
    ``"default"`` is rare in practice: first-run rendering writes non-secret
    defaults as real values, so even fresh installs report ``file`` — the
    branch covers a hand-edited config whose line was removed."""
    if _env_var_is_set(COMICVINE_IGNORED_PUBLISHERS_ENV_VAR):
        return "env"
    stored = _read_config(Path(settings.config_dir) / CONFIG_FILENAME)
    if "comicvine_ignored_publishers" in stored:
        return "file"
    return "default"


class ComicVineKeyStatus(BaseModel):
    """Configured-state + source for the ComicVine key — NEVER the value."""

    configured: bool
    #: One of ``"unset"``, ``"file"`` (set in ``config.yaml``), or
    #: ``"environment"`` (set via ``FORAGERR_COMICVINE_API_KEY``).
    source: str


class IgnoredPublishersStatus(BaseModel):
    """The ignored-publishers list VALUE + its source (FRG-UI-031).

    Unlike the key this is not a secret: the value is echoed so the Settings
    field can render it for editing. ``source`` is ``"env"``/``"file"``/``"default"``
    — an env-managed value renders read-only (the env var would shadow a write)."""

    value: str
    source: str


class GeneralConfig(BaseModel):
    """The Settings → General resource: the ComicVine credential STATUS plus the
    editable ignored-publishers list.

    The key is a write-only credential surface — the read reports whether it is
    configured and its source but never the value or any substring of it
    (FRG-API-018 / FRG-META-002). The ignored-publishers list IS echoed (not a
    secret) with its source so the field can render editable or read-only
    (FRG-UI-031).
    """

    comicvine_api_key: ComicVineKeyStatus
    comicvine_ignored_publishers: IgnoredPublishersStatus

    @classmethod
    def from_settings(cls, settings: Settings) -> "GeneralConfig":
        key_source = _comicvine_source(settings)
        return cls(
            comicvine_api_key=ComicVineKeyStatus(
                configured=key_source != "unset", source=key_source
            ),
            comicvine_ignored_publishers=IgnoredPublishersStatus(
                value=settings.comicvine_ignored_publishers,
                source=_ignored_publishers_source(settings),
            ),
        )


class GeneralConfigUpdate(BaseModel):
    """PUT body for the General resource (FRG-API-018 / FRG-UI-031).

    ``comicvine_api_key``: a blank value means "leave the stored key unchanged"
    (the write-only "leave blank to keep" convention), NOT "clear it".

    ``comicvine_ignored_publishers``: ``None`` (the default, or an omitted field)
    means "leave the stored list unchanged"; a STRING — including the empty
    string — sets it, so an operator CAN clear the list to hide nothing. The two
    fields are independent, so a save that only touches one leaves the other.
    """

    comicvine_api_key: str = ""
    comicvine_ignored_publishers: str | None = None


class ComicVineTestResponse(BaseModel):
    """A passing ComicVine connectivity/credential test result (never the key)."""

    success: bool
    message: str


@router.get("/general", response_model=GeneralConfig)
async def get_general(request: Request) -> GeneralConfig:
    """Report the ComicVine key's configured status + source (FRG-API-018).

    Never returns the key value: only ``{configured, source}``."""
    return GeneralConfig.from_settings(request.app.state.settings)


@router.put("/general", response_model=GeneralConfig)
async def put_general(body: GeneralConfigUpdate, request: Request):
    """Persist UI-written General settings and apply them live (FRG-API-018 /
    FRG-UI-031). The ComicVine key and the ignored-publishers list are handled
    INDEPENDENTLY so a save that touches only one leaves the other alone.

    - **ComicVine key**: a BLANK key keeps the stored value (write-only "leave
      blank to keep") — no write, no env check. A non-blank key when the key is
      env-supplied (``source == "environment"``) is REJECTED as
      environment-managed (a 409 naming the env var) rather than persisting a
      value the environment would shadow on reload (design decision 4).
    - **Ignored publishers**: ``None`` (omitted) leaves the stored list; a string
      (including empty, to hide nothing) is written — unless the list is
      env-managed, which is rejected the same way as the key.
    - Applied fields are merged into ``config.yaml`` through the documented
      writer via the shared ``_apply`` read-modify-write-reload, which swaps
      ``app.state.settings`` (live-apply, no restart) and re-registers secrets
      with the log-redaction filter.
    """
    current: Settings = request.app.state.settings
    updates: dict[str, Any] = {}

    key = body.comicvine_api_key.strip()
    if key:
        if _comicvine_source(current) == "environment":
            raise ApiError(
                409,
                "the ComicVine API key is managed by the "
                f"{COMICVINE_KEY_ENV_VAR} environment variable, which takes "
                "precedence over the config file; unset it to edit the key here",
                field="comicvine_api_key",
            )
        updates["comicvine_api_key"] = key

    if body.comicvine_ignored_publishers is not None:
        if _ignored_publishers_source(current) == "env":
            raise ApiError(
                409,
                "the ignored-publishers list is managed by the "
                f"{COMICVINE_IGNORED_PUBLISHERS_ENV_VAR} environment variable, "
                "which takes precedence over the config file; unset it to edit "
                "the list here",
                field="comicvine_ignored_publishers",
            )
        updates["comicvine_ignored_publishers"] = body.comicvine_ignored_publishers

    if not updates:
        # Nothing to change (blank key, list untouched); report current status.
        return GeneralConfig.from_settings(current)

    return await _apply(request, updates, GeneralConfig)


@router.post("/comicvine/test", response_model=ComicVineTestResponse)
async def comicvine_test(request: Request) -> ComicVineTestResponse:
    """Validate the EFFECTIVE ComicVine key against ComicVine (FRG-API-018).

    Mirrors the indexer test-button contract (FRG-IDX-003): a passing result is
    a 200 ``{success, message}``; a credential failure is a field-precise 400
    (``field="comicvine_api_key"``) carrying the shared static credential
    sentence, and any other reachability failure a generic 400. Persists
    NOTHING and NEVER puts the key value in the response body or a log line —
    the auth path logs one static line and raises the static message, never the
    key or the raw upstream text.
    """
    settings = request.app.state.settings
    factory = comicvine_factory(settings)
    try:
        async with ComicVineClient(settings, factory) as cv:
            result = await cv.suggest_series(_COMICVINE_TEST_TERM)
    except ComicVineAuthError as exc:
        # Static message + static log line — never interpolate the key or the
        # exception's raw text, so no credential value can reach body or log.
        logger.warning("comicvine connectivity test rejected: API key missing or invalid")
        raise ApiError(
            400,
            f"comicvine test failed: {COMICVINE_CREDENTIAL_MESSAGE}",
            field="comicvine_api_key",
        ) from exc
    except ComicVineError as exc:
        logger.warning("comicvine connectivity test failed: %s", type(exc).__name__)
        raise ApiError(400, f"comicvine test failed: {exc}") from exc

    # suggest_series swallows every NON-auth upstream failure (5xx, timeout,
    # rate-limit, malformed) into complete=False rather than raising — with
    # one deliberate exception: ComicVineBudgetExhausted propagates
    # (FRG-META-016) and lands in the ComicVineError branch above. For the
    # swallowed class, a naive "no exception ⇒ success" would report a broken
    # service as healthy.
    # Treat an incomplete result as a reachability failure with a STATIC message
    # (no dynamic interpolation: defense-in-depth against a redacted-but-present
    # URL-with-key slipping into the body, even though OutboundHttpError text is
    # pre-redacted).
    if not result.complete:
        logger.warning("comicvine connectivity test failed: upstream unreachable or errored")
        raise ApiError(
            400,
            "comicvine test failed: service unreachable or returned an error",
            field=None,
        )

    return ComicVineTestResponse(
        success=True, message="ComicVine reachable; credentials accepted"
    )


async def _apply(request: Request, updates: dict[str, Any], resource: type[BaseModel]):
    """Validate ``updates`` against the full config, persist, and reload.

    The whole read-modify-write-reload runs under ``_config_write_lock`` so two
    concurrent PUTs can't lost-update one another. On a validation failure NOTHING
    is changed and a 400 in the uniform shape is returned, each offending field
    named under the ``settings.`` prefix. The persisted file is rewritten through
    the documented-config renderer (comments preserved) and written atomically.
    """
    async with _config_write_lock:
        current: Settings = request.app.state.settings
        config_dir = Path(current.config_dir)
        config_file = config_dir / CONFIG_FILENAME

        stored = _read_config(config_file)
        merged = {**stored, **updates}
        merged.pop("config_dir", None)  # environment-only

        try:
            new_settings = Settings(config_dir=config_dir, **merged)
        except ValidationError as exc:
            return JSONResponse(
                status_code=400,
                content=error_body(
                    "config validation failed",
                    [
                        {
                            "field": f"settings.{'.'.join(str(p) for p in err['loc'])}",
                            "message": err.get("msg", "invalid value"),
                        }
                        for err in exc.errors()
                    ],
                ),
            )

        # Validation passed: persist (documented + atomic) and swap in the reload.
        atomic_write_text(config_file, render_documented_config(merged))
        for secret in new_settings.secret_fields().values():
            register_secret(secret.get_secret_value())
        request.app.state.settings = new_settings
        # Command workers read settings from the service's HandlerContext at
        # execution time; without this refresh they keep the boot-time snapshot
        # and a UI-saved ComicVine key never reaches refresh/import/credit runs
        # until restart (FRG-META-018). Worker POOL SIZES stay boot-time.
        commands = getattr(request.app.state, "commands", None)
        if commands is not None:
            commands.context.settings = new_settings
        return resource.from_settings(new_settings)


def _read_config(config_file: Path) -> dict[str, Any]:
    if not config_file.exists():
        return {}
    loaded = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    return loaded if isinstance(loaded, dict) else {}
