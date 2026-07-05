"""Process-wide config-dir resolution for the DDL area.

The GetComics search provider persists politeness stats under ``<config>/``
(FRG-DDL-006) but runs inside the change-4 search pipeline, which does not
thread :class:`~foragerr.config.Settings` down to a per-indexer search. Rather
than widen every pipeline signature, the provider resolves the config dir once,
here, from the same env/config the running app loaded — and tests pass an
explicit ``config_dir`` so this fallback is never on the deterministic path.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

logger = logging.getLogger("foragerr.ddl.state")

_config_dir: Path | None = None


def resolve_config_dir() -> Path:
    """The app's config dir, cached; a temp dir if settings cannot load."""
    global _config_dir
    if _config_dir is not None:
        return _config_dir
    try:
        from foragerr.config import load_settings

        _config_dir = Path(load_settings().config_dir)
    except Exception as exc:  # noqa: BLE001 — never let this fail a search
        _config_dir = Path(tempfile.gettempdir()) / "foragerr-ddl"
        logger.warning(
            "ddl: falling back to a temp state dir (%s): %s", _config_dir, exc
        )
    return _config_dir


def set_config_dir(path: Path | None) -> None:
    """Override the cached config dir — TEST-ONLY / startup hook."""
    global _config_dir
    _config_dir = Path(path) if path is not None else None


__all__ = ["resolve_config_dir", "set_config_dir"]
