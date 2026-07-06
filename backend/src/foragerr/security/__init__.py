"""Shared filesystem- and archive-safety utilities (FRG-SEC-003/004).

Single ownership of the two cross-cutting safety primitives that every path- or
archive-touching area (import pipeline, renamer, DDL, OPDS, cover cache) depends
on:

- :mod:`foragerr.security.paths` — `safe_path_component()` (the one component
  sanitizer, relocated here from ``library.paths``) and `safe_join()`, the only
  sanctioned way to construct a destination path under a managed root
  (FRG-SEC-004).
- :mod:`foragerr.security.archives` — `inspect_archive()`, the one shared
  archive-safety utility enforcing member-count / decompressed-size / nesting
  limits and rejecting zip-slip, symlink, and absolute member names before any
  extraction (FRG-SEC-003, FRG-PP-006).
"""

from __future__ import annotations

from foragerr.security.archives import (
    DEFAULT_ARCHIVE_LIMITS,
    ArchiveLimits,
    ArchiveReport,
    inspect_archive,
)
from foragerr.security.paths import (
    PathConfinementError,
    safe_join,
    safe_path_component,
)

__all__ = [
    "DEFAULT_ARCHIVE_LIMITS",
    "ArchiveLimits",
    "ArchiveReport",
    "PathConfinementError",
    "inspect_archive",
    "safe_join",
    "safe_path_component",
]
