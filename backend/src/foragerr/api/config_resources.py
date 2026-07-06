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
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from foragerr.api.errors import error_body
from foragerr.config import CONFIG_FILENAME, Settings, render_documented_config
from foragerr.config_migrations import atomic_write_text
from foragerr.logging import register_secret
from foragerr.naming import (
    DEFAULT_FILE_TEMPLATE,
    DEFAULT_FOLDER_TEMPLATE,
    _TOKEN_ALIASES,
)

router = APIRouter(prefix="/config", tags=["config"])

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
        return resource.from_settings(new_settings)


def _read_config(config_file: Path) -> dict[str, Any]:
    if not config_file.exists():
        return {}
    loaded = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    return loaded if isinstance(loaded, dict) else {}
