"""Tracked-download state machine + failure loop (FRG-DL-007/011/012/013).

The tracking area drives ``tracked_downloads`` from what every enabled download
client reports, entirely through the pinned
:class:`~foragerr.downloads.clients.base.DownloadClient` protocol — it never
branches on the concrete client type, so a SABnzbd item and a built-in-DDL item
flow the identical path (the "DDL is just another client" property). Nothing here
imports the ddl package: the failure loop consumes ``ClientItem.status == failed``
and is protocol-agnostic.

Structure follows Sonarr's split (design decision 3):

- a **cheap check** every refresh — list items from all clients, match each to its
  ``grab_history`` row by download id (re-parsing an unmatched title as secondary
  evidence), and upsert the per-download state/status/messages; and
- a **state-advancing process** — the failure loop that promotes ``failed_pending``
  to ``failed``, writes the multi-field blocklist row, emits the failure event, and
  enqueues an automatic re-search (FRG-DL-011/012/013).

Change 5 only DRIVES the ``downloading → import_pending | import_blocked | failed
| ignored`` subset; ``importing`` / ``imported`` belong to change 6's import
pipeline and are treated as terminal here (never regressed).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass, field
from typing import ClassVar, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.commands.registry import BaseCommand, register_command, register_handler
from foragerr.commands.service import HandlerContext
from foragerr.db import queue_event, utcnow
from foragerr.downloads.clients.base import ClientItem, ClientItemStatus, DownloadClient
from foragerr.downloads.errors import DownloadClientError
from foragerr.downloads.models import (
    SOURCE_DDL,
    SOURCE_INDEXER,
    BlocklistRow,
    DownloadClientRow,
    GrabHistoryRow,
    TrackedDownloadRow,
)
from foragerr.downloads.registry import (
    ClientBuildContext,
    PROTOCOL_DDL,
    get_implementation,
)
from foragerr.downloads.repo import (
    load_download_clients,
    load_mappings,
    load_settings,
)
from foragerr.downloads.state import (
    TRACKED_STATUS_ERROR,
    TRACKED_STATUS_OK,
    TRACKED_STATUS_WARNING,
    TrackedDownloadState,
)
from foragerr.events import Event
from foragerr.library.models import IssueRow, SeriesRow
from foragerr.parser import parse
from foragerr.providers.backoff import ProviderBackoff

logger = logging.getLogger("foragerr.downloads.tracking")

#: States change 5 treats as TERMINAL: never regressed by a later observation.
#: ``failed`` / ``ignored`` are terminal for this change; ``importing`` /
#: ``imported`` belong to change 6 and must never be driven backwards here.
_TERMINAL_STATES = frozenset(
    {
        TrackedDownloadState.FAILED,
        TrackedDownloadState.IGNORED,
        TrackedDownloadState.IMPORTING,
        TrackedDownloadState.IMPORTED,
    }
)


# --- events (FRG-DL-007/011) -------------------------------------------------


@dataclass(frozen=True, slots=True)
class TrackedStateChanged(Event):
    """A tracked download's persisted state changed (FRG-DL-007)."""

    download_id: str
    state: str
    status: str
    series_id: int | None
    issue_id: int | None


@dataclass(frozen=True, slots=True)
class DownloadFailedEvent(Event):
    """A tracked download failed; carries what the blocklist + re-search need.

    ``issues`` is every ``(series_id, issue_id)`` the failed download satisfied
    (from ``grab_history``), so the re-search covers a multi-issue release
    (FRG-DL-011).
    """

    download_id: str
    source_title: str | None
    guid: str | None
    indexer_id: int | None
    indexer_name: str | None
    size_bytes: int | None
    publish_date: dt.datetime | None
    protocol: str | None
    source: str | None
    issues: tuple[tuple[int, int], ...]


# --- observations: one client item as the tracking loop sees it --------------


@dataclass(frozen=True, slots=True)
class ClientObservation:
    """One :class:`ClientItem` tagged with its originating client (FRG-DL-007).

    The reconcile core consumes ONLY this — a protocol string plus the uniform
    item — so it never depends on the concrete client (SAB or DDL).
    """

    client_id: int | None
    client_name: str | None
    protocol: str
    item: ClientItem


# --- status-message (de)serialization ---------------------------------------


def _encode_messages(messages: list[str]) -> str | None:
    return json.dumps(messages) if messages else None


def decode_messages(raw: str | None) -> list[str]:
    """Decode a ``tracked_downloads.status_messages`` JSON value (never raises)."""
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return [raw]
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


# --- item -> (state, status, messages) classification (the cheap check) ------


def _classify_item(item: ClientItem) -> tuple[TrackedDownloadState, str, list[str]]:
    """Map a polled :class:`ClientItem` to a target tracked state (FRG-DL-007).

    Encrypted / failed converge on ``failed_pending`` (the failure loop promotes
    it); a completed-but-unimportable warning (e.g. an unmapped remote path) maps
    to ``import_blocked``; a clean completion maps to ``import_pending`` (awaiting
    change 6). Everything in flight is ``downloading``.
    """
    if item.encrypted or item.status is ClientItemStatus.FAILED:
        reason = item.reason or (
            "encrypted / password-protected archive"
            if item.encrypted
            else "download failed"
        )
        return TrackedDownloadState.FAILED_PENDING, TRACKED_STATUS_ERROR, [reason]
    if item.status is ClientItemStatus.WARNING:
        return (
            TrackedDownloadState.IMPORT_BLOCKED,
            TRACKED_STATUS_WARNING,
            [item.reason or "completed but not importable — check remote path mapping"],
        )
    if item.status is ClientItemStatus.COMPLETED:
        return TrackedDownloadState.IMPORT_PENDING, TRACKED_STATUS_OK, []
    if item.status is ClientItemStatus.PAUSED:
        return TrackedDownloadState.DOWNLOADING, TRACKED_STATUS_WARNING, ["paused"]
    return TrackedDownloadState.DOWNLOADING, TRACKED_STATUS_OK, []


def _should_advance(current: TrackedDownloadState, target: TrackedDownloadState) -> bool:
    """Whether an observed ``target`` state may overwrite ``current`` (FRG-DL-007).

    Terminal states are never regressed, and a completed/blocked item is not
    dragged back to ``downloading`` by a stale queue slot; an in-flight failure
    already recorded is not un-failed.
    """
    if current in _TERMINAL_STATES:
        return False
    if (
        current
        in (TrackedDownloadState.IMPORT_PENDING, TrackedDownloadState.IMPORT_BLOCKED)
        and target is TrackedDownloadState.DOWNLOADING
    ):
        return False
    if current is TrackedDownloadState.FAILED_PENDING and target in (
        TrackedDownloadState.DOWNLOADING,
        TrackedDownloadState.IMPORT_PENDING,
        TrackedDownloadState.IMPORT_BLOCKED,
    ):
        return False
    return True


# --- identity resolution for a newly-seen download ---------------------------


async def _adopt_unmatched(
    session: AsyncSession, title: str, now: dt.datetime
) -> tuple[int | None, int | None, str]:
    """Re-parse an unmatched client item's title and adopt-or-mark-unknown.

    An embedded ``[__issueid__]`` tag WINS over heuristics (FRG-DL-007): it names
    our own issue id directly. Otherwise a matching-key + issue-number heuristic is
    tried. Anything unresolved is recorded as unknown. Never raises — a parse or
    lookup failure degrades to unknown so the refresh cannot crash.
    """
    try:
        parsed = parse(title, reference_year=now.year)
        if parsed.issue_id:
            try:
                iid = int(parsed.issue_id)
            except (TypeError, ValueError):
                iid = None
            if iid is not None:
                issue = await session.get(IssueRow, iid)
                if issue is not None:
                    return (
                        issue.series_id,
                        issue.id,
                        f"adopted via issue-id tag onto issue {iid}",
                    )
        if parsed.matching_key and parsed.issue is not None:
            series = (
                await session.execute(
                    select(SeriesRow).where(
                        SeriesRow.matching_key == parsed.matching_key
                    )
                )
            ).scalars().first()
            if series is not None and parsed.issue.display is not None:
                issue = (
                    await session.execute(
                        select(IssueRow).where(
                            IssueRow.series_id == series.id,
                            IssueRow.issue_number == parsed.issue.display,
                        )
                    )
                ).scalars().first()
                if issue is not None:
                    return series.id, issue.id, "adopted via title match"
    except Exception:  # noqa: BLE001 — a bad title must never crash the refresh
        logger.exception("tracking: failed to re-parse unmatched item title")
        return None, None, "unmatched download (re-parse failed)"
    return None, None, "unmatched download (unknown)"


# --- reconcile: the cheap check ---------------------------------------------


async def reconcile_downloads(
    db,
    observations: list[ClientObservation],
    *,
    now: dt.datetime | None = None,
) -> None:
    """Upsert ``tracked_downloads`` from the current client observations.

    Matches each observation to its ``grab_history`` row by download id, drives
    the state machine (persisting transitions + ok/warning/error status + human
    messages, emitting a :class:`TrackedStateChanged` per change), and marks a
    download that has vanished from every client (while still ``downloading``) as
    ``failed_pending``. Restart-safe: all state lives in the row. The failure
    loop runs separately in :func:`process_failures`.
    """
    now = now or utcnow()
    seen: set[str] = {obs.item.download_id for obs in observations}
    async with db.write_session() as session:
        existing = (
            (await session.execute(select(TrackedDownloadRow))).scalars().all()
        )
        by_key = {(r.client_id, r.download_id): r for r in existing}

        for obs in observations:
            item = obs.item
            row = by_key.get((obs.client_id, item.download_id))
            target, status, messages = _classify_item(item)
            is_new = row is None
            if row is None:
                row = await _create_tracked_row(session, obs, now)
                by_key[(obs.client_id, item.download_id)] = row
                # New rows carry the adoption message when unmatched.
                base_messages = decode_messages(row.status_messages)
            else:
                base_messages = []
            _refresh_mutable_fields(row, item, now)
            if _should_advance(TrackedDownloadState(row.state), target):
                # A brand-new row records grabbed -> its first observed state, so
                # its creation is itself a transition worth an event.
                changed = is_new or row.state != target.value
                row.state = target.value
                row.status = status
                combined = base_messages + messages
                row.status_messages = _encode_messages(combined)
                row.updated_at = now
                if changed:
                    queue_event(
                        session,
                        TrackedStateChanged(
                            download_id=row.download_id,
                            state=row.state,
                            status=row.status,
                            series_id=row.series_id,
                            issue_id=row.issue_id,
                        ),
                    )

        # Vanished-before-completion: a still-downloading row absent from every
        # client this cycle is a failure (FRG-DL-011).
        for row in existing:
            if (
                row.download_id not in seen
                and row.state == TrackedDownloadState.DOWNLOADING.value
            ):
                row.state = TrackedDownloadState.FAILED_PENDING.value
                row.status = TRACKED_STATUS_ERROR
                row.status_messages = _encode_messages(
                    ["download vanished from the client before completing"]
                )
                row.updated_at = now
                queue_event(
                    session,
                    TrackedStateChanged(
                        download_id=row.download_id,
                        state=row.state,
                        status=row.status,
                        series_id=row.series_id,
                        issue_id=row.issue_id,
                    ),
                )


async def _create_tracked_row(
    session: AsyncSession, obs: ClientObservation, now: dt.datetime
) -> TrackedDownloadRow:
    """Create a tracked row, matched to grab_history or adopted/unknown."""
    item = obs.item
    grabs = (
        (
            await session.execute(
                select(GrabHistoryRow).where(
                    GrabHistoryRow.download_id == item.download_id
                )
            )
        )
        .scalars()
        .all()
    )
    if grabs:
        first = grabs[0]
        series_id, issue_id = first.series_id, first.issue_id
        source = first.source
        indexer_name = first.indexer_name
        messages: list[str] = []
    else:
        series_id, issue_id, message = await _adopt_unmatched(session, item.title, now)
        source = SOURCE_DDL if obs.protocol == PROTOCOL_DDL else SOURCE_INDEXER
        indexer_name = None
        messages = [message]
    row = TrackedDownloadRow(
        download_id=item.download_id,
        client_id=obs.client_id,
        client_name=obs.client_name,
        protocol=obs.protocol,
        source=source,
        state=TrackedDownloadState.DOWNLOADING.value,
        status=TRACKED_STATUS_OK,
        status_messages=_encode_messages(messages),
        series_id=series_id,
        issue_id=issue_id,
        indexer_name=indexer_name,
        title=item.title,
        category=item.category,
        total_size=item.total_size,
        remaining_size=item.remaining_size,
        estimated_time=_estimated_seconds(item.estimated_time),
        output_path=item.output_path,
        encrypted=item.encrypted,
        added_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    return row


def _refresh_mutable_fields(
    row: TrackedDownloadRow, item: ClientItem, now: dt.datetime
) -> None:
    """Refresh the cheap per-poll fields (sizes, path, eta) without touching the
    state machine (which :func:`reconcile_downloads` gates via ``_should_advance``)."""
    row.title = item.title
    row.category = item.category
    row.total_size = item.total_size
    row.remaining_size = item.remaining_size
    row.estimated_time = _estimated_seconds(item.estimated_time)
    if item.output_path is not None:
        row.output_path = item.output_path
    row.encrypted = row.encrypted or item.encrypted
    row.updated_at = now


def _estimated_seconds(value: float | None) -> int | None:
    return int(round(value)) if value is not None else None


# --- process_failures: the state-advancing process (FRG-DL-011/012/013) ------


@dataclass(frozen=True, slots=True)
class _FailureInfo:
    download_id: str
    issues: tuple[tuple[int, int], ...]


async def process_failures(
    db,
    *,
    commands=None,
    settings=None,
    now: dt.datetime | None = None,
) -> list[_FailureInfo]:
    """Promote every ``failed_pending`` download to ``failed`` and self-heal.

    For each: write the multi-field blocklist row (FRG-DL-012), emit a
    :class:`DownloadFailedEvent`, then — once the failed transition has committed
    — enqueue an automatic ``issue-search`` for every affected issue when
    auto-redownload is enabled (FRG-DL-013). The command backbone dedups equal
    ``(name, payload)`` commands still queued/started, so a storm of failures for
    the same issue collapses to one re-search. Returns the failures processed.
    """
    now = now or utcnow()
    infos: list[_FailureInfo] = []
    async with db.write_session() as session:
        rows = (
            (
                await session.execute(
                    select(TrackedDownloadRow).where(
                        TrackedDownloadRow.state
                        == TrackedDownloadState.FAILED_PENDING.value
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            grabs = (
                (
                    await session.execute(
                        select(GrabHistoryRow).where(
                            GrabHistoryRow.download_id == row.download_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            issues = _affected_issues(row, grabs)
            _write_blocklist_row(session, row, grabs, now)
            row.state = TrackedDownloadState.FAILED.value
            row.status = TRACKED_STATUS_ERROR
            row.updated_at = now
            first = grabs[0] if grabs else None
            queue_event(
                session,
                DownloadFailedEvent(
                    download_id=row.download_id,
                    source_title=(first.title if first else row.title),
                    guid=first.guid if first else None,
                    indexer_id=first.indexer_id if first else None,
                    indexer_name=(first.indexer_name if first else row.indexer_name),
                    size_bytes=(first.size_bytes if first else row.total_size),
                    publish_date=first.pub_date if first else None,
                    protocol=(first.protocol if first else row.protocol),
                    source=(first.source if first else row.source),
                    issues=issues,
                ),
            )
            infos.append(_FailureInfo(download_id=row.download_id, issues=issues))

    await _enqueue_research(commands, settings, infos)
    return infos


def _affected_issues(
    row: TrackedDownloadRow, grabs: list[GrabHistoryRow]
) -> tuple[tuple[int, int], ...]:
    """Every (series_id, issue_id) the failed download satisfied (FRG-DL-011)."""
    pairs: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for g in grabs:
        if g.series_id is not None and g.issue_id is not None:
            pair = (g.series_id, g.issue_id)
            if pair not in seen:
                seen.add(pair)
                pairs.append(pair)
    if not pairs and row.series_id is not None and row.issue_id is not None:
        pairs.append((row.series_id, row.issue_id))
    return tuple(pairs)


def _write_blocklist_row(
    session: AsyncSession,
    row: TrackedDownloadRow,
    grabs: list[GrabHistoryRow],
    now: dt.datetime,
) -> None:
    """Write the multi-field blocklist row for a failed release (FRG-DL-012)."""
    first = grabs[0] if grabs else None
    protocol = first.protocol if first else row.protocol
    is_ddl = protocol == SOURCE_DDL or (first and first.source == SOURCE_DDL)
    session.add(
        BlocklistRow(
            series_id=row.series_id,
            issue_id=row.issue_id,
            source_title=(first.title if first else row.title),
            guid=first.guid if first else None,
            indexer_id=first.indexer_id if first else None,
            indexer_name=(first.indexer_name if first else row.indexer_name),
            size_bytes=(first.size_bytes if first else row.total_size),
            publish_date=first.pub_date if first else None,
            protocol=protocol,
            source=(first.source if first else row.source),
            source_url=(first.link if (first and is_ddl) else None),
            download_id=row.download_id,
            message="; ".join(decode_messages(row.status_messages)) or None,
            created_at=now,
        )
    )


async def _enqueue_research(commands, settings, infos: list[_FailureInfo]) -> None:
    """Enqueue an automatic re-search per affected issue (FRG-DL-013).

    Runs after the failed transition has committed (a separate write session).
    Deduped both within this call and by the command backbone across cycles, so a
    failure storm cannot spawn a storm of duplicate searches.
    """
    if commands is None:
        return
    auto = getattr(settings, "auto_redownload_failed", True) if settings else True
    if not auto:
        return
    queued: set[tuple[int, int]] = set()
    for info in infos:
        for series_id, issue_id in info.issues:
            if (series_id, issue_id) in queued:
                continue
            queued.add((series_id, issue_id))
            await commands.enqueue(
                "issue-search",
                {"series_id": series_id, "issue_id": issue_id},
                triggered_by="failure",
            )


# --- client enumeration (the I/O boundary) -----------------------------------


async def load_enabled_clients(
    db, *, settings=None
) -> list[tuple[DownloadClientRow, DownloadClient]]:
    """Instantiate every enabled, runnable download client (FRG-DL-007).

    Enumerates the ``download_clients`` provider rows (a corrupt row is already
    isolated by ``load_download_clients``), skipping disabled rows and any
    implementation without a wired client factory (e.g. ddl before its area
    registers one). Built through the same registry factory + build context the
    grab resolver uses.
    """
    from foragerr.downloads import make_download_factory

    listing = await load_download_clients(db)
    factory = make_download_factory(settings) if settings is not None else None
    backoff = ProviderBackoff(db)
    clients: list[tuple[DownloadClientRow, DownloadClient]] = []
    for row in listing.healthy:
        if not row.enabled:
            continue
        impl = get_implementation(row.implementation)
        if impl.client_factory is None:
            continue
        settings_model = load_settings(row.implementation, row.settings)
        mappings = await load_mappings(db, row.id)
        ctx = ClientBuildContext(
            row=row,
            settings=settings_model,
            db=db,
            http_factory=factory,
            backoff=backoff,
            mappings=mappings,
            app_settings=settings,
        )
        clients.append((row, impl.client_factory(ctx)))
    return clients


async def build_client_for_id(
    db, client_id: int, *, settings=None
) -> DownloadClient | None:
    """Build the live client for one ``download_clients`` row id, or ``None``."""
    for row, client in await load_enabled_clients(db, settings=settings):
        if row.id == client_id:
            return client
    return None


async def collect_observations(
    clients: list[tuple[DownloadClientRow, DownloadClient]],
) -> list[ClientObservation]:
    """Poll ``get_items()`` on every client, isolating each (FRG-DL-007).

    A client that is unreachable (or otherwise raises) is logged and skipped —
    one downed client never crashes the whole refresh.
    """
    observations: list[ClientObservation] = []
    for row, client in clients:
        try:
            items = await client.get_items()
        except DownloadClientError as exc:
            logger.warning(
                "tracking: client unreachable; skipping this cycle",
                extra={"client_id": row.id, "client_name": row.name, "error": str(exc)},
            )
            continue
        except Exception:  # noqa: BLE001 — never let one client crash the refresh
            logger.exception(
                "tracking: client get_items raised; skipping this cycle",
                extra={"client_id": row.id, "client_name": row.name},
            )
            continue
        for item in items:
            observations.append(
                ClientObservation(
                    client_id=row.id,
                    client_name=row.name,
                    protocol=row.protocol,
                    item=item,
                )
            )
    return observations


async def run_tracking(ctx: HandlerContext) -> str:
    """One full tracking refresh: collect → reconcile → process failures."""
    now = utcnow()
    clients = await load_enabled_clients(ctx.db, settings=ctx.settings)
    observations = await collect_observations(clients)
    await reconcile_downloads(ctx.db, observations, now=now)
    infos = await process_failures(
        ctx.db, commands=ctx.commands, settings=ctx.settings, now=now
    )
    return (
        f"tracked {len(observations)} client item(s) across {len(clients)} "
        f"client(s); {len(infos)} failure(s) processed"
    )


# --- scheduled + event-triggered command ------------------------------------


@register_command
class TrackDownloadsCommand(BaseCommand):
    """Poll every enabled client and advance the tracking state machine.

    On the ``download`` pool (size 1, so client polling is serialized and polite),
    scheduled ~every minute and event-triggered on grab/import. Serialized within
    its own exclusivity group so two refreshes never overlap (FRG-DL-007).
    """

    name: Literal["track-downloads"] = "track-downloads"
    workload_class: ClassVar[str] = "download"
    exclusivity_group: ClassVar[str | None] = "track-downloads"


@register_handler("track-downloads")
async def _handle_track_downloads(
    command: TrackDownloadsCommand, ctx: HandlerContext
) -> str:
    return await run_tracking(ctx)


__all__ = [
    "ClientObservation",
    "DownloadFailedEvent",
    "TrackDownloadsCommand",
    "TrackedStateChanged",
    "build_client_for_id",
    "collect_observations",
    "decode_messages",
    "load_enabled_clients",
    "process_failures",
    "reconcile_downloads",
    "run_tracking",
]
