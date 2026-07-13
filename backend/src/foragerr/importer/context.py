"""The import pipeline's runtime context (FRG-PP-001).

One immutable value carries everything the source-agnostic stages need that is
*not* per-candidate: the reference year for parsing, the library root, the config
directory (quarantine base), the free-space margin, and the renaming
configuration (templates + enable switch + transfer mode). The flows commands
build this once per run and hand it to :func:`foragerr.importer.pipeline.gather`
and :func:`~foragerr.importer.pipeline.import_candidate`.

A ``free_space_probe`` seam lets tests force a low-space condition without a real
full volume; it defaults to the real :func:`shutil.disk_usage`-backed probe.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from foragerr.importer import fileops
from foragerr.importer.decisions import DUPLICATE_CONSTRAINT_LARGER_SIZE
from foragerr.naming import DEFAULT_FILE_TEMPLATE, DEFAULT_FOLDER_TEMPLATE
from foragerr.parser.vocab import ARCHIVE_EXTENSIONS

#: ``HandlerContext.offload``-compatible callable (``daemon_offload`` in
#: production): runs a blocking function on a thread off the shared event loop.
OffloadFn = Callable[..., Awaitable[Any]]

#: Minimum plausible archive size; anything smaller is treated as junk/sample
#: (a real comic page scan set is far larger than this floor).
DEFAULT_JUNK_SIZE_FLOOR_BYTES = 100 * 1024

#: Maximum directory depth a rescan/download walk descends (bounded walk).
DEFAULT_MAX_WALK_DEPTH = 8

#: Shared command exclusivity group for every file-mutating importer command
#: (the completed-download drain AND the per-series rescan). Both carry it so at
#: most one library-mutating importer runs at a time regardless of the ``pp``
#: pool size (``workers_pp`` may be up to 4) — double-import safety must not rest
#: on the pool being size 1 (FRG-SER-010).
#:
#: Defined on this dependency-light leaf (and re-exported unchanged from
#: ``foragerr.importer.__init__``) for definition-site clarity: a flows module
#: that only needs the group string + :class:`ImportContext` (e.g.
#: ``library.flows.rename``) imports it from here. This is NOT an import-cost
#: decouple — importing ``foragerr.importer.context`` still executes the
#: ``foragerr.importer`` package ``__init__`` (Python parent-package semantics),
#: which loads the full pipeline + ORM registration regardless. The actual
#: cycle protection is the isolated-importability regression guard in
#: ``tests/test_nfr_startup.py`` (FRG-NFR-001), which imports each leaf as the
#: sole entry point in a fresh subprocess. The value is byte-identical to the
#: historical package constant.
IMPORT_FILE_MUTATION_GROUP = "import-file-mutation"


@dataclass(frozen=True, slots=True)
class ImportContext:
    """Per-run pipeline configuration (FRG-PP-001). Immutable; no per-candidate state."""

    library_root: str
    config_dir: str
    reference_year: int
    free_space_margin_bytes: int = fileops.DEFAULT_FREE_SPACE_MARGIN_BYTES
    junk_size_floor_bytes: int = DEFAULT_JUNK_SIZE_FLOOR_BYTES
    max_walk_depth: int = DEFAULT_MAX_WALK_DEPTH
    archive_extensions: tuple[str, ...] = ARCHIVE_EXTENSIONS
    rename_enabled: bool = False
    file_template: str = DEFAULT_FILE_TEMPLATE
    folder_template: str = DEFAULT_FOLDER_TEMPLATE
    transfer_mode: fileops.TransferMode = fileops.TransferMode.MOVE
    #: How an existing-library import treats files already under the library
    #: (FRG-IMP-023, m2-existing-library-import design decision 4): ``in_place``
    #: (default) registers a candidate that is already at its computed
    #: destination — or anywhere under the series folder when renaming is
    #: disabled — WITHOUT ``place_file``; ``move`` routes every candidate
    #: through the normal placement/rename path exactly as downloads do.
    library_import_mode: str = "in_place"
    #: Recycle-bin root for upgrade-replaced files (FRG-PP-013). ``""`` = the
    #: superseded file is permanently deleted on replacement (no bin configured).
    recycle_bin_path: str = ""
    #: Days recycle-bin entries are retained before housekeeping prunes them
    #: (``0`` = keep forever). Carried for the housekeeping prune, not execute.
    recycle_bin_retention_days: int = 0
    #: Same-rung duplicate arbitration constraint (FRG-PP-014):
    #: ``larger-size`` (default) or ``preferred-format``.
    duplicate_constraint: str = DUPLICATE_CONSTRAINT_LARGER_SIZE
    #: Duplicate-dump root the losing file of a duplicate resolution moves to
    #: (dated subfolders, FRG-PP-014). ``""`` = the normal replaced-file
    #: disposal (recycle bin, or permanent delete) applies. Deliberately NOT a
    #: recycle bin — it is never marked, so retention pruning never touches it.
    duplicate_dump_path: str = ""
    #: Whether the import pipeline writes a ComicInfo.xml tag into cbz archives on
    #: import (FRG-PP-017). OFF by default; consumed by the ComicInfo write half
    #: (defined by the tagging area). The embedded-metadata READ (FRG-IMP-024) is
    #: always active and is NOT gated by this flag.
    comicinfo_tag_enabled: bool = False
    now: dt.datetime | None = None
    #: Free-space probe seam (path → free bytes); default is the real probe.
    free_space_probe: Callable[[str], int] = field(default=fileops.free_bytes)
    #: Optional offload seam for the FS-heavy work (the multi-GB ``place_file``
    #: copy/fsync and archive inspection). The flows commands pass
    #: ``ctx.offload`` so that work runs on a daemon thread instead of stalling
    #: the shared event loop; ``None`` (tests/direct callers) runs it inline.
    offload: OffloadFn | None = None
    #: Per-run cache of a series' parsed-issue index (``series_id`` → index), so
    #: reconciliation parses each series' issues once per run rather than once
    #: per candidate (built lazily; keyed off the run-scoped context instance).
    issue_index_cache: dict[int, list] = field(
        default_factory=dict, compare=False, repr=False
    )


#: Maps a config ``Settings`` attribute to the :class:`ImportContext` seam it
#: feeds (design decisions 3-4). Any attribute absent on the supplied object is
#: skipped, so a minimal stub settings keeps the engine defaults.
_SETTINGS_TO_CTX: dict[str, str] = {
    "rename_enabled": "rename_enabled",
    "file_naming_template": "file_template",
    "folder_naming_template": "folder_template",
    "recycle_bin_path": "recycle_bin_path",
    "recycle_bin_retention_days": "recycle_bin_retention_days",
    "comicinfo_tag_on_import": "comicinfo_tag_enabled",
    "duplicate_constraint": "duplicate_constraint",
    "duplicate_dump_path": "duplicate_dump_path",
    "library_import_mode": "library_import_mode",
}


def media_management_fields(settings: Any) -> dict[str, Any]:
    """The naming/media-management :class:`ImportContext` seams sourced from the
    config ``Settings`` (FRG-PP-012/013, design decisions 3-4).

    Duck-typed on ``settings`` (read by attribute, missing attributes skipped) so
    this stays free of a ``config`` import — the pipeline context is pure — and a
    minimal stub settings (some tests pass only ``config_dir``) keeps the engine
    defaults. Returns an empty mapping for ``None`` (bare/direct callers)."""
    if settings is None:
        return {}
    fields: dict[str, Any] = {
        ctx_key: getattr(settings, s_attr)
        for s_attr, ctx_key in _SETTINGS_TO_CTX.items()
        if hasattr(settings, s_attr)
    }
    mode = getattr(settings, "import_transfer_mode", None)
    if mode is not None:
        fields["transfer_mode"] = fileops.TransferMode(mode)
    return fields


__all__ = [
    "DEFAULT_JUNK_SIZE_FLOOR_BYTES",
    "DEFAULT_MAX_WALK_DEPTH",
    "IMPORT_FILE_MUTATION_GROUP",
    "ImportContext",
    "OffloadFn",
    "media_management_fields",
]
