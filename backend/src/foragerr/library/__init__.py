"""The library domain: root folders, series, issues, issue files.

Implements FRG-SER-001..004, 008, 009 and the FRG-DB-008 typed/sentinel-free
schema discipline for the library tables. Public surface:

- :mod:`foragerr.library.models` — ORM models (`RootFolderRow`, `SeriesRow`,
  `IssueRow`, `IssueFileRow`).
- :mod:`foragerr.library.repo` — CRUD helpers, the derived `wanted_issues()`
  selectable (FRG-SER-004 — there is no stored `wanted` column anywhere),
  and per-request `series_statistics()` (FRG-SER-009).
- :mod:`foragerr.library.paths` — `safe_path_component()`, the M1 series
  path template, under-root validation, and directory rename.
- :mod:`foragerr.library.ordering` — the persisted issue ordering-key
  encoding, built on the shared parser ordering implementation.

Out of scope here (later changes build on top of this package): the add/
refresh/scan flows, the ComicVine client, and the API routers.
"""

from __future__ import annotations

from foragerr.library.models import (
    ISSUE_TYPES,
    MONITOR_NEW_ITEMS_POLICIES,
    SERIES_STATUSES,
    IssueFileRow,
    IssueRow,
    RootFolderRow,
    SeriesRow,
)
from foragerr.library.ordering import ordering_key_for
from foragerr.library.paths import (
    PathNotUnderRootError,
    build_series_path,
    rename_series_directory,
    safe_path_component,
    series_folder_name,
    validate_under_root,
)
from foragerr.library.repo import SeriesStatistics, series_statistics, wanted_issues

__all__ = [
    "ISSUE_TYPES",
    "MONITOR_NEW_ITEMS_POLICIES",
    "SERIES_STATUSES",
    "IssueFileRow",
    "IssueRow",
    "PathNotUnderRootError",
    "RootFolderRow",
    "SeriesRow",
    "SeriesStatistics",
    "build_series_path",
    "ordering_key_for",
    "rename_series_directory",
    "safe_path_component",
    "series_folder_name",
    "series_statistics",
    "validate_under_root",
    "wanted_issues",
]
