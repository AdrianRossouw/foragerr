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

from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from foragerr.api.errors import error_body
from foragerr.config import CONFIG_FILENAME, Settings
from foragerr.logging import register_secret

router = APIRouter(prefix="/config", tags=["config"])


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
    recycle_bin_path: str
    recycle_bin_retention_days: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "MediaManagementConfig":
        return cls(
            import_transfer_mode=settings.import_transfer_mode,
            library_import_mode=settings.library_import_mode,
            recycle_bin_path=settings.recycle_bin_path,
            recycle_bin_retention_days=settings.recycle_bin_retention_days,
        )


@router.get("/naming", response_model=NamingConfig)
async def get_naming(request: Request) -> NamingConfig:
    """Return the current typed naming values (FRG-API-013)."""
    return NamingConfig.from_settings(request.app.state.settings)


@router.put("/naming", response_model=NamingConfig)
async def put_naming(body: NamingConfig, request: Request):
    """Validate + persist naming settings, re-loading app.state.settings."""
    return _apply(request, body.model_dump(), NamingConfig)


@router.get("/mediamanagement", response_model=MediaManagementConfig)
async def get_media_management(request: Request) -> MediaManagementConfig:
    """Return the current typed media-management values (FRG-API-013)."""
    return MediaManagementConfig.from_settings(request.app.state.settings)


@router.put("/mediamanagement", response_model=MediaManagementConfig)
async def put_media_management(body: MediaManagementConfig, request: Request):
    """Validate + persist media-management settings, re-loading app.state.settings."""
    return _apply(request, body.model_dump(), MediaManagementConfig)


def _apply(request: Request, updates: dict[str, Any], resource: type[BaseModel]):
    """Validate ``updates`` against the full config, persist, and reload.

    On a validation failure NOTHING is changed and a 400 in the uniform shape is
    returned, each offending field named under the ``settings.`` prefix.
    """
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

    # Validation passed: persist and swap in the reloaded settings.
    stored.update(updates)
    stored.pop("config_dir", None)
    config_file.write_text(yaml.safe_dump(stored, sort_keys=False), encoding="utf-8")
    for secret in new_settings.secret_fields().values():
        register_secret(secret.get_secret_value())
    request.app.state.settings = new_settings
    return resource.from_settings(new_settings)


def _read_config(config_file: Path) -> dict[str, Any]:
    if not config_file.exists():
        return {}
    loaded = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    return loaded if isinstance(loaded, dict) else {}
