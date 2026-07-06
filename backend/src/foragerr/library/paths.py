"""The M1 series-folder template and series-directory moves (FRG-SER-008).

Implements the path-construction half of design decisions 10/11: series folder
names are built only from sanitized components — never raw ComicVine titles —
and any per-series path override must resolve under a registered root folder.

Component sanitization itself is *not* owned here: `safe_path_component` was
relocated to :mod:`foragerr.security.paths` under single ownership (FRG-SEC-004,
change 6 design decision 5). The series-folder *template* is likewise no longer
rendered here: change 6 moves that to the one token renaming engine
(:func:`foragerr.importer.renamer.render_series_folder`, SER-008 template
ownership transfer, FRG-PP-010). :func:`series_folder_name` now delegates to it,
byte-for-byte unchanged for existing rows. Systematic destination-path
confinement (safe-join) lives in ``security.paths``, and so does the read-side
containment check for stored paths: ``validate_under_root`` relocated there at
change-7 integration (same single-ownership rule). The names are re-exported
here unchanged for existing callers; ``PathNotUnderRootError`` is now an alias
of :class:`foragerr.security.paths.PathConfinementError`.
"""

from __future__ import annotations

import os
from pathlib import Path

from foragerr.security.paths import (
    PathConfinementError as PathNotUnderRootError,
)
from foragerr.security.paths import (
    validate_under_root,
)

__all__ = [
    "PathNotUnderRootError",
    "build_series_path",
    "rename_series_directory",
    "series_folder_name",
    "validate_under_root",
]


def series_folder_name(title: str, start_year: int | None) -> str:
    """The M1 fixed series-folder template (FRG-SER-008 decision 11).

    ``{Series Title (safe)} ({start_year})``. ``start_year`` is optional in
    the schema (a defensive allowance beyond the spec, which assumes it is
    always known from ComicVine) — when absent the year suffix is simply
    omitted rather than rendering a placeholder.

    Rendered by the change-6 token engine (SER-008 ownership transfer,
    FRG-PP-010): this is a thin delegation so there is exactly one implementation
    of the series-folder template, with no behaviour change for existing rows.
    """
    from foragerr.importer.renamer import render_series_folder

    return render_series_folder(title, start_year)


def build_series_path(root_folder_path: str | Path, title: str, start_year: int | None) -> Path:
    """The default series path: ``{root}/{safe series title} ({start_year})``."""
    return Path(root_folder_path) / series_folder_name(title, start_year)


def rename_series_directory(old_path: str | Path, new_path: str | Path) -> None:
    """Move/rename a series' on-disk directory.

    If ``old_path`` does not exist yet (e.g. the add flow hasn't scanned/
    created it), the new directory is simply created so later steps find it
    in place — there is nothing to roll back in that case. Otherwise this
    performs an ``os.rename`` (atomic on the same filesystem); any
    ``OSError`` propagates so the caller's write-transaction rolls back the
    paired DB row change (design decision 12 — "rollback on failure" is a
    property of running this inside the same ``write_session()`` as the row
    update, not of this function alone).
    """
    old = Path(old_path)
    new = Path(new_path)
    if old == new:
        return
    new.parent.mkdir(parents=True, exist_ok=True)
    if not old.exists():
        new.mkdir(parents=True, exist_ok=True)
        return
    os.rename(old, new)
