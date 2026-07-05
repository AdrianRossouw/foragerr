"""Safe path components, the M1 series-folder template, and path moves.

Implements the path-construction half of design decisions 10/11
(FRG-SER-008, FRG-NFR-012): series folder names are built only from
sanitized components — never raw ComicVine titles — and any per-series path
override must resolve under a registered root folder. Full filesystem
confinement beyond component sanitization (safe-join against a resolved
root, symlink escape, etc.) is explicitly out of scope here — that is
FRG-SEC-004, owned by change 6's renaming engine; this module only owns
safe *construction* of a path from trusted components (a root folder path)
plus one untrusted title string.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

#: Windows/DOS reserved device names — reserved with or without an extension
#: (``CON``, ``CON.txt``, and even ``CON.tar.gz`` are all unwritable on
#: Windows), so the check is against the segment before the *first* dot.
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class PathNotUnderRootError(ValueError):
    """A series path does not resolve under any registered root folder."""


def safe_path_component(raw: str | None, *, fallback: str = "untitled") -> str:
    """Reduce ``raw`` to one filesystem-safe path *segment* (FRG-NFR-012).

    - Path separators (``/``, ``\\``) are replaced with spaces, so an
      embedded traversal sequence like ``../`` can never introduce a real
      directory boundary once this segment is joined onto a root path.
    - Control characters (including CR/LF) are stripped.
    - Runs of whitespace collapse to single spaces.
    - Leading/trailing dots and spaces are stripped (the Windows/NTFS
      trailing-dot-or-space rule; this also fully erases inputs that are
      pure traversal sequences like ``..`` or ``../..``, since after
      separator-replacement they contain only dots and spaces).
    - Windows reserved device names are de-reserved with a leading
      underscore, matched with or without a following extension.
    - Never returns an empty string — falls back to ``fallback``.
    """
    text = raw or ""
    text = text.replace("/", " ").replace("\\", " ")
    text = _CONTROL_RE.sub(" ", text)
    text = " ".join(text.split())
    text = text.strip(" .")
    if not text:
        text = fallback
    stem = text.split(".", 1)[0].upper()
    if stem in _RESERVED_NAMES:
        text = f"_{text}"
    return text


def series_folder_name(title: str, start_year: int | None) -> str:
    """The M1 fixed series-folder template (FRG-SER-008 decision 11).

    ``{Series Title (safe)} ({start_year})``. ``start_year`` is optional in
    the schema (a defensive allowance beyond the spec, which assumes it is
    always known from ComicVine) — when absent the year suffix is simply
    omitted rather than rendering a placeholder.
    """
    safe_title = safe_path_component(title)
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
