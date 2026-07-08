"""The add-series entrypoint (FRG-SER-005, FRG-SER-006).

``add_series`` is a plain async function the future API router calls directly
(it is NOT a command handler). It validates everything up front, persists one
series row carrying its ``add_options``, and enqueues the ``refresh-series``
command that drives the rest of the chain (refresh -> scan -> optional
search). Validation failures raise :class:`SeriesValidationError` and leave no
row, command, or path behind.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from foragerr.commands.service import CommandService
from foragerr.config import Settings
from foragerr.db import Database
from foragerr.http import HttpClientFactory
from foragerr.library import repo
from foragerr.library.models import RootFolderRow, SeriesRow
from foragerr.library.paths import (
    PathNotUnderRootError,
    build_series_path,
    validate_under_root,
)
from foragerr.metadata import (
    COMICVINE_CREDENTIAL_MESSAGE,
    ComicVineAuthError,
    ComicVineClient,
    ComicVineError,
    SeriesRecord,
)
from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow

from foragerr.library.flows._common import (
    RefreshSeriesCommand,
    SeriesValidationError,
    comicvine_factory,
    encode_add_options,
    validate_monitor_new_items,
    validate_monitor_strategy,
)


@dataclass(frozen=True)
class AddSeriesResult:
    """What :func:`add_series` returns to its (API) caller.

    ``series`` is the persisted row (detached but fully loaded — safe to read
    scalar attributes); ``refresh_command_id`` is the id of the enqueued
    ``refresh-series`` command, which the API layer echoes in its 201 body —
    ``None`` when the caller opted out via ``enqueue_refresh=False`` (it owns
    the refresh itself, e.g. the library-import flow's direct awaited refresh).
    """

    series: SeriesRow
    refresh_command_id: int | None


async def add_series(
    db: Database,
    settings: Settings,
    *,
    cv_volume_id: int,
    root_folder_id: int,
    commands: CommandService,
    format_profile_id: int | None = None,
    monitor_strategy: str = "all",
    monitor_new_items: str = "all",
    search_on_add: bool = False,
    path_override: str | None = None,
    enqueue_refresh: bool = True,
    factory: HttpClientFactory | None = None,
) -> AddSeriesResult:
    """Validate and add a series, then enqueue its refresh chain.

    Rejects (raising :class:`SeriesValidationError`, no writes) when:

    * ``monitor_strategy`` / ``monitor_new_items`` are not recognised;
    * the ComicVine volume does not exist or cannot be fetched cleanly;
    * ``root_folder_id`` / ``format_profile_id`` reference no real row;
    * ``cv_volume_id`` already has a series row;
    * ``path_override`` does not resolve under a registered root folder.

    On success: persists the series (with ``add_options`` encoding the
    strategy / monitor-new-items policy / search-on-add flag as canonical
    JSON) inside one write transaction, then enqueues
    ``refresh-series`` for it — unless ``enqueue_refresh=False``, for callers
    that run the refresh themselves (the library-import flow awaits it
    directly so files can match issues deterministically; enqueuing here too
    would double every ComicVine fetch and scan).
    """
    validate_monitor_strategy(monitor_strategy)
    validate_monitor_new_items(monitor_new_items)

    factory = factory or comicvine_factory(settings)

    # --- ComicVine existence check (network; outside any write lock) --------
    try:
        async with ComicVineClient(settings, factory) as cv:
            record: SeriesRecord = await cv.get_volume(cv_volume_id)
    except ComicVineAuthError as exc:
        # Credential failure gets the ONE shared actionable wording every
        # surface uses (m2-lookup-error-surfacing design, Decision 5) —
        # static text, never the exception's own message, so no key material
        # can leak into the validation error.
        raise SeriesValidationError(
            f"comicvine volume {cv_volume_id} could not be fetched: "
            f"{COMICVINE_CREDENTIAL_MESSAGE}"
        ) from exc
    except ComicVineError as exc:
        # Unavailable / malformed / rate-limited all reject cleanly —
        # a volume we cannot fetch is not one we add (no partial writes).
        raise SeriesValidationError(
            f"comicvine volume {cv_volume_id} could not be fetched: {exc}"
        ) from exc

    title = record.name or f"Volume {cv_volume_id}"

    # --- single write transaction: validate the rest, then insert ----------
    async with db.write_session() as session:
        root = await session.get(RootFolderRow, root_folder_id)
        if root is None:
            raise SeriesValidationError(
                f"root folder {root_folder_id} is not registered"
            )

        resolved_profile_id = await _resolve_format_profile_id(
            session, format_profile_id
        )

        existing = await session.scalar(
            select(SeriesRow.id).where(SeriesRow.cv_volume_id == cv_volume_id)
        )
        if existing is not None:
            raise SeriesValidationError(
                f"comicvine volume {cv_volume_id} is already in the library"
            )

        if path_override is not None:
            roots = await repo.list_root_folders(session)
            try:
                path = str(validate_under_root(path_override, [r.path for r in roots]))
            except PathNotUnderRootError as exc:
                raise SeriesValidationError(str(exc)) from exc
        else:
            path = str(build_series_path(root.path, title, record.start_year))

        path_taken = await session.scalar(
            select(SeriesRow.id).where(SeriesRow.path == path)
        )
        if path_taken is not None:
            raise SeriesValidationError(
                f"path {path!r} is already used by another series"
            )

        series = await repo.create_series(
            session,
            cv_volume_id=cv_volume_id,
            title=title,
            publisher=record.publisher,
            start_year=record.start_year,
            monitor_new_items=monitor_new_items,
            format_profile_id=resolved_profile_id,
            root_folder_id=root_folder_id,
            path=path,
            description_sanitized=record.description,
            add_options=encode_add_options(
                monitor_strategy=monitor_strategy,
                monitor_new_items=monitor_new_items,
                search_on_add=search_on_add,
            ),
        )

        # Auto-derive the franchise group for this run (FRG-SER-016) — a
        # display-only link; issue creation / wanted logic is untouched.
        await repo.apply_autogrouping(session, series)

    # --- enqueue the refresh chain (after commit) --------------------------
    if not enqueue_refresh:
        return AddSeriesResult(series=series, refresh_command_id=None)
    refresh = await commands.enqueue(
        "refresh-series", {"series_id": series.id}, triggered_by="add-series"
    )
    return AddSeriesResult(series=series, refresh_command_id=refresh.id)


async def _resolve_format_profile_id(session, format_profile_id: int | None) -> int:
    """Resolve the profile id, defaulting to the seeded "Default" profile."""
    if format_profile_id is None:
        default_id = await session.scalar(
            select(FormatProfileRow.id).where(
                FormatProfileRow.name == DEFAULT_PROFILE_NAME
            )
        )
        if default_id is None:  # pragma: no cover - seed guarantees this exists
            raise SeriesValidationError("default format profile is not seeded")
        return default_id
    exists = await session.get(FormatProfileRow, format_profile_id)
    if exists is None:
        raise SeriesValidationError(
            f"format profile {format_profile_id} does not exist"
        )
    return format_profile_id
