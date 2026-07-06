"""Filesystem path confinement: the single component sanitizer and safe-join
(FRG-SEC-004).

This module owns *all* path-component sanitization. `safe_path_component`
(relocated here from ``library.paths`` — one module owns path safety, design
decision 5) reduces one untrusted string to a single filesystem-safe segment;
`safe_join` is the only sanctioned way to build a destination path under a
managed root, guaranteeing via realpath containment that the result cannot
escape that root even through a pre-existing symlink in the tree.

There is deliberately no second, independent copy of component sanitization
anywhere in the codebase (FRG-SEC-004 scenario 4): callers that need to sanitize
a path segment import `safe_path_component` from here.
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


class PathConfinementError(ValueError):
    """A constructed path escaped (or would escape) its managed root."""


def safe_path_component(raw: str | None, *, fallback: str = "untitled") -> str:
    """Reduce ``raw`` to one filesystem-safe path *segment* (FRG-SEC-004).

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


def _is_within(root_real: str, candidate_real: str) -> bool:
    """True if ``candidate_real`` is ``root_real`` or lives beneath it.

    Uses :func:`os.path.commonpath` (segment-aware, so ``/a/bc`` is *not*
    treated as inside ``/a/b``) and treats a cross-drive / cross-root pair as
    outside rather than raising.
    """
    if candidate_real == root_real:
        return True
    try:
        return os.path.commonpath([root_real, candidate_real]) == root_real
    except ValueError:
        # Different drives (Windows) or a mix of absolute/relative — treat as
        # not contained.
        return False


def safe_join(root: str | os.PathLike[str], *parts: str) -> Path:
    """Join ``parts`` under ``root``, guaranteed to stay inside ``root``.

    The only sanctioned constructor for import/renamer/cover destination paths
    (FRG-SEC-004). ``root`` is trusted (a configured managed root — library
    root, ``/config`` cache, or download staging); every element of ``parts``
    is untrusted or derived and is reduced to a single safe segment via
    :func:`safe_path_component` (separators neutralized, ``..`` erased,
    reserved names de-reserved, never empty), so no part can introduce a
    directory boundary or a traversal.

    As defence in depth beyond component sanitization, the assembled path is
    realpath-resolved and confirmed to remain within ``root``; this also
    catches escape via a *pre-existing symlink* already sitting in the tree
    (a symlinked prefix that points outside the root). Any escape raises
    :class:`PathConfinementError`.

    Returns the (unresolved) joined path spelled under the caller-supplied
    ``root`` so the destination keeps the intended naming.
    """
    root_path = Path(root)
    candidate = root_path
    for part in parts:
        candidate = candidate / safe_path_component(part)

    root_real = os.path.realpath(root_path)
    candidate_real = os.path.realpath(candidate)
    if not _is_within(root_real, candidate_real):
        raise PathConfinementError(
            f"refusing to construct {candidate!s}: resolves to {candidate_real!r} "
            f"which is outside the managed root {root_real!r}"
        )
    return candidate


def validate_under_root(
    path: str | os.PathLike[str],
    root_folders: "list[str | Path] | tuple[str | Path, ...]",
) -> Path:
    """Resolve ``path`` and confirm it sits at or under one of ``root_folders``.

    The canonical containment check for an already-stored full path (FRG-SEC-004)
    — the read-side counterpart to :func:`safe_join`'s write-side construction.
    Used wherever a persisted path (an ``issue_files`` row served by OPDS, a
    series path override) must be proven to live inside a managed root before it
    is trusted. Resolution follows symlinks, so a row pointing through a link
    that escapes every root is rejected. Raises :class:`PathConfinementError`;
    returns the resolved path so callers can persist a normalized form.
    """
    candidate = Path(os.path.realpath(Path(path)))
    for root in root_folders:
        if _is_within(os.path.realpath(Path(root)), str(candidate)):
            return candidate
    raise PathConfinementError(
        f"{candidate} is not under any registered root folder"
    )


__all__ = [
    "PathConfinementError",
    "safe_join",
    "safe_path_component",
    "validate_under_root",
]
