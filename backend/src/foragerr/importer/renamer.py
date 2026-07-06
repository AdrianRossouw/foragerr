"""Token-based renaming engine and folder templates (FRG-PP-009, FRG-PP-010).

The renaming engine itself lives in the dependency-free :mod:`foragerr.naming`
leaf so that :mod:`foragerr.config` (which validates naming templates) can share
it without importing the whole ``importer`` package — that import would form a
``config`` → ``importer`` → ``downloads`` → … → ``config`` cycle. This module
re-exports the engine unchanged, so ``from foragerr.importer.renamer import
render_filename`` (and the ``_TOKEN_ALIASES`` token vocabulary the settings UI
reads) keep working exactly as before. See :mod:`foragerr.naming` for the full
engine documentation, the token vocabulary, and the round-trip contract.
"""

from __future__ import annotations

from foragerr.naming import (
    DEFAULT_FILE_TEMPLATE,
    DEFAULT_FOLDER_TEMPLATE,
    DEFAULT_MAX_FILENAME_BYTES,
    RenameFields,
    _TOKEN_ALIASES,
    render,
    render_filename,
    render_folder_segments,
    render_series_folder,
)

__all__ = [
    "DEFAULT_FILE_TEMPLATE",
    "DEFAULT_FOLDER_TEMPLATE",
    "DEFAULT_MAX_FILENAME_BYTES",
    "RenameFields",
    "render",
    "render_filename",
    "render_folder_segments",
    "render_series_folder",
]
