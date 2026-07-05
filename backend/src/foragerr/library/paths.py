"""The M1 series-folder template and series-directory moves (FRG-SER-008).

Implements the path-construction half of design decisions 10/11: series folder
names are built only from sanitized components — never raw ComicVine titles —
and any per-series path override must resolve under a registered root folder.

Component sanitization itself is *not* owned here: `safe_path_component` was
relocated to :mod:`foragerr.security.paths` under single ownership (FRG-SEC-004,
change 6 design decision 5). This module consumes that one sanitizer to render
the fixed series-folder template; systematic destination-path confinement
(safe-join) also lives in ``security.paths``.
"""

from __future__ import annotations

import os
from pathlib import Path

from foragerr.security import paths as _security_paths


class PathNotUnderRootError(ValueError):
    """A series path does not resolve under any registered root folder."""


def series_folder_name(title: str, start_year: int | None) -> str:
    """The M1 fixed series-folder template (FRG-SER-008 decision 11).

    ``{Series Title (safe)} ({start_year})``. ``start_year`` is optional in
    the schema (a defensive allowance beyond the spec, which assumes it is
    always known from ComicVine) — when absent the year suffix is simply
    omitted rather than rendering a placeholder.
    """
    safe_title = _security_paths.safe_path_component(title)
    if start_year is None:
        return safe_title
    return f"{safe_title} ({start_year})"


def build_series_path(root_folder_path: str | Path, title: str, start_year: int | None) -> Path:
    """The default series path: ``{root}/{safe series title} ({start_year})``."""
    return Path(root_folder_path) / series_folder_name(title, start_year)


def validate_under_root(path: str | Path, root_folders: "list[str | Path] | tuple[str | Path, ...]") -> Path:
    """Resolve ``path`` and confirm it sits at or under a registered root.

    Raises :class:`PathNotUnderRootError` otherwise. Returns the resolved
    path so callers can persist a normalized form.
    """
    candidate = Path(path).resolve()
    for root in root_folders:
        root_path = Path(root).resolve()
        if candidate == root_path or root_path in candidate.parents:
            return candidate
    raise PathNotUnderRootError(
        f"{candidate} is not under any registered root folder"
    )


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
