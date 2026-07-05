"""OPDS 1.2 catalog area (FRG-OPDS-001..006).

:func:`register_opds` is the app-factory extension point (mirrors
``register_api``/``register_database``): it mounts the OPDS router at the
configured base path (``settings.opds_base_path``, default ``/opds``). Serves
UNAUTHENTICATED content — the confinement / id-only design lives in
:mod:`foragerr.opds.router`.
"""

from __future__ import annotations

from fastapi import FastAPI

from foragerr.opds.router import build_opds_router

__all__ = ["register_opds", "build_opds_router"]


def register_opds(app: FastAPI) -> None:
    """Mount the OPDS catalog at the configured base path."""
    base_path = app.state.settings.opds_base_path
    app.include_router(build_opds_router(base_path), prefix=base_path)
