"""The shared import pipeline, renaming engine, and import history (change 6).

This package lands completed downloads and rescanned files into the library
through ONE pipeline (evidence aggregation → import decisions → safe execution),
renames them with the token engine under the round-trip contract, and records an
``import_history`` event for every outcome.

Public API (the surface the flows commands — ``ProcessImportsCommand`` /
``RescanSeriesCommand``, implemented outside this package — code against):

- :class:`~foragerr.importer.context.ImportContext` — the per-run config value.
- :class:`~foragerr.importer.sources.CompletedDownloadSource`,
  :class:`~foragerr.importer.sources.RescanSource`,
  :class:`~foragerr.importer.sources.ImportCandidate` — the two intakes (data).
- :func:`~foragerr.importer.pipeline.gather` — run a source's intake.
- :func:`~foragerr.importer.pipeline.import_candidate` — aggregate → decide →
  execute one candidate, writing the ``issue_files`` row and the history event
  inside the caller's ``write_session``; returns an
  :class:`~foragerr.importer.pipeline.ImportOutcome`
  (:class:`~foragerr.importer.pipeline.ImportStatus` IMPORTED / BLOCKED /
  FAILED). It never mutates ``tracked_downloads`` — the flows command owns those
  status-guarded transitions (change-5 concurrency seam).
- :mod:`~foragerr.importer.history` — the event vocabulary and per-issue/global
  queries (``events_for_issue`` / ``events_for_download`` / ``all_events``).
- :mod:`~foragerr.importer.renamer` — the token engine (``render_filename`` /
  ``render_series_folder``) that now owns change-3's series-folder template.

Importing this package maps the :class:`~foragerr.importer.models.ImportHistoryRow`
ORM model onto ``Base.metadata`` (same convention as the downloads area).
"""

from __future__ import annotations

from foragerr.importer.context import (
    IMPORT_FILE_MUTATION_GROUP,
    ImportContext,
    media_management_fields,
)
from foragerr.importer.models import ImportHistoryRow
from foragerr.importer.pipeline import (
    ImportOutcome,
    ImportStatus,
    gather,
    import_candidate,
)
from foragerr.importer.sources import (
    CompletedDownloadSource,
    ImportCandidate,
    LibraryImportSource,
    ManualImportSource,
    ManualOverride,
    RescanSource,
)

#: Shared command exclusivity group for every file-mutating importer command
#: (the completed-download drain AND the per-series rescan). Both carry it so at
#: most one library-mutating importer runs at a time regardless of the ``pp``
#: pool size (``workers_pp`` may be up to 4) — double-import safety must not rest
#: on the pool being size 1 (FRG-SER-010). Canonically defined on the
#: dependency-light :mod:`foragerr.importer.context` leaf and re-exported here
#: unchanged (byte-identical public API) so flows modules needing only the group
#: string can import the leaf without the full pipeline (FRG-NFR-001).

__all__ = [
    "IMPORT_FILE_MUTATION_GROUP",
    "CompletedDownloadSource",
    "ImportCandidate",
    "ImportContext",
    "ImportHistoryRow",
    "ImportOutcome",
    "ImportStatus",
    "LibraryImportSource",
    "ManualImportSource",
    "ManualOverride",
    "RescanSource",
    "gather",
    "import_candidate",
    "media_management_fields",
]
