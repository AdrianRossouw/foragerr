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
from collections.abc import Callable
from dataclasses import dataclass, field

from foragerr.importer import fileops
from foragerr.importer.renamer import DEFAULT_FILE_TEMPLATE, DEFAULT_FOLDER_TEMPLATE
from foragerr.parser.vocab import ARCHIVE_EXTENSIONS

#: Minimum plausible archive size; anything smaller is treated as junk/sample
#: (a real comic page scan set is far larger than this floor).
DEFAULT_JUNK_SIZE_FLOOR_BYTES = 100 * 1024

#: Maximum directory depth a rescan/download walk descends (bounded walk).
DEFAULT_MAX_WALK_DEPTH = 8


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
    rename_enabled: bool = True
    file_template: str = DEFAULT_FILE_TEMPLATE
    folder_template: str = DEFAULT_FOLDER_TEMPLATE
    transfer_mode: fileops.TransferMode = fileops.TransferMode.MOVE
    now: dt.datetime | None = None
    #: Free-space probe seam (path → free bytes); default is the real probe.
    free_space_probe: Callable[[str], int] = field(default=fileops.free_bytes)


__all__ = [
    "DEFAULT_JUNK_SIZE_FLOOR_BYTES",
    "DEFAULT_MAX_WALK_DEPTH",
    "ImportContext",
]
