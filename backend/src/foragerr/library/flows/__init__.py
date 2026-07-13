"""Library business-logic flows (change 3: FRG-SER-005/006/007/014, FRG-META-008).

The layer between the (frozen) ``foragerr.library`` domain/repo and
``foragerr.metadata`` ComicVine client on one side, and the future FastAPI
routers on the other. Public entrypoints the API layer calls directly:

- :func:`add_series` -> :class:`AddSeriesResult` (validate, persist, enqueue
  the ``refresh-series`` chain);
- :func:`edit_series` / :func:`delete_series`.

Importing this package registers the three chained commands and their
handlers as a side effect (``refresh-series`` -> ``scan-series`` -> optional
``series-search``), so ``foragerr.app`` need only import it once for the
decorators to take effect.
"""

from __future__ import annotations

from foragerr.library.flows._common import (
    AddOptions,
    BOOKTYPE_EDIT_ACTIONS,
    BooktypeEdit,
    GROUP_EDIT_ACTIONS,
    GroupEdit,
    MAX_ALIAS_LENGTH,
    MONITOR_STRATEGIES,
    RefreshSeriesCommand,
    ScanSeriesCommand,
    SeriesNotFoundError,
    SeriesRefreshed,
    SeriesSearchCommand,
    SeriesValidationError,
    comicvine_factory,
    decode_add_options,
    decode_aliases,
    encode_add_options,
    encode_aliases,
)
from foragerr.library.flows.add import AddSeriesResult, add_series
from foragerr.library.flows.convert import (
    ConvertIssueCommand,
    ConvertReport,
    ConvertSeriesCommand,
    convert_issue,
    convert_series,
)
from foragerr.library.flows.edit_delete import (
    DeleteSeriesFilesCommand,
    IssueFileNotFoundError,
    delete_issue_file,
    delete_series,
    edit_series,
)
from foragerr.library.flows.library_import import (
    LIBRARY_IMPORT_PROPOSAL_CAP,
    LibraryImportCommand,
    LibraryImportScanBlockedError,
    LibraryImportScanCommand,
    decode_group_files,
    decode_rejections,
    encode_group_files,
    encode_rejections,
    execute_library_import,
    importable_volume,
    scan_library_root,
)
from foragerr.library.flows.refresh import refresh_series
from foragerr.library.flows.rename import (
    RenameSeriesCommand,
    preview_series_renames,
    rename_series,
)
from foragerr.library.flows.rescan import (
    RescanReport,
    RescanSeriesCommand,
    rescan_series,
)
from foragerr.library.flows.scan import scan_series

# Import for the handler-registration side effect (``@register_handler``).
from foragerr.library.flows import search as _search  # noqa: F401

__all__ = [
    "AddOptions",
    "AddSeriesResult",
    "BOOKTYPE_EDIT_ACTIONS",
    "BooktypeEdit",
    "ConvertIssueCommand",
    "ConvertReport",
    "ConvertSeriesCommand",
    "GROUP_EDIT_ACTIONS",
    "GroupEdit",
    "DeleteSeriesFilesCommand",
    "IssueFileNotFoundError",
    "LIBRARY_IMPORT_PROPOSAL_CAP",
    "LibraryImportCommand",
    "LibraryImportScanBlockedError",
    "LibraryImportScanCommand",
    "MAX_ALIAS_LENGTH",
    "MONITOR_STRATEGIES",
    "RefreshSeriesCommand",
    "RenameSeriesCommand",
    "RescanReport",
    "RescanSeriesCommand",
    "ScanSeriesCommand",
    "SeriesNotFoundError",
    "SeriesRefreshed",
    "SeriesSearchCommand",
    "SeriesValidationError",
    "add_series",
    "comicvine_factory",
    "convert_issue",
    "convert_series",
    "decode_add_options",
    "decode_aliases",
    "decode_group_files",
    "decode_rejections",
    "delete_issue_file",
    "delete_series",
    "edit_series",
    "encode_add_options",
    "encode_aliases",
    "encode_group_files",
    "encode_rejections",
    "execute_library_import",
    "importable_volume",
    "preview_series_renames",
    "refresh_series",
    "rename_series",
    "rescan_series",
    "scan_library_root",
    "scan_series",
]
