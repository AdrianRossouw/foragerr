"""Shared helpers for the tracking + failure-loop tests (FRG-DL-006..013).

Deliberately client-agnostic: a :class:`FakeClient` implements the pinned
``DownloadClient`` protocol so the tracking loop can be exercised with SAB-shaped
and DDL-shaped items WITHOUT importing the real SAB or ddl areas — proving the
loop branches on nothing but the uniform ``ClientItem``. Grab-history / tracked /
blocklist rows carry plain-integer series/issue ids (no FK), so most tests use
synthetic ids; :func:`seed_library` builds real rows only where a nested
series/issue or an ``[__issueid__]`` adoption needs one.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from sqlalchemy import select

from foragerr.db import utcnow
from foragerr.downloads.clients.base import ClientItem, ClientItemStatus
from foragerr.downloads.models import (
    SOURCE_INDEXER,
    BlocklistRow,
    GrabHistoryRow,
    TrackedDownloadRow,
)
from foragerr.downloads.state import TrackedDownloadState


def make_item(
    download_id: str,
    *,
    status: ClientItemStatus = ClientItemStatus.DOWNLOADING,
    title: str = "Spawn 001 (2024)",
    category: str = "comics",
    total_size: int = 100,
    remaining_size: int = 40,
    estimated_time: float | None = 90.0,
    output_path: str | None = None,
    encrypted: bool = False,
    reason: str | None = None,
) -> ClientItem:
    return ClientItem(
        download_id=download_id,
        title=title,
        category=category,
        total_size=total_size,
        remaining_size=remaining_size,
        estimated_time=estimated_time,
        output_path=output_path,
        status=status,
        encrypted=encrypted,
        reason=reason,
    )


class FakeClient:
    """A :class:`DownloadClient` returning canned items; records removals."""

    def __init__(self, items: list[ClientItem]) -> None:
        self._items = items
        self.removed: list[tuple[str, bool]] = []
        self.imported: list[str] = []

    async def test(self):  # pragma: no cover - unused by tracking
        return SimpleNamespace(success=True, message="ok", version=None, warnings=())

    async def download(self, request) -> str:  # pragma: no cover - unused
        return "fake"

    async def get_items(self) -> list[ClientItem]:
        return list(self._items)

    async def remove(self, item: ClientItem, delete_data: bool) -> None:
        self.removed.append((item.download_id, delete_data))

    async def mark_imported(self, item: ClientItem) -> None:  # pragma: no cover
        self.imported.append(item.download_id)


def fake_row(*, client_id: int = 1, name: str = "SAB", protocol: str = "usenet"):
    """A stand-in ``download_clients`` row (only id/name/protocol are read)."""
    return SimpleNamespace(id=client_id, name=name, protocol=protocol)


class FakeCommands:
    """Records ``enqueue`` calls (no dedup) for asserting the re-search loop."""

    def __init__(self) -> None:
        self.enqueued: list[tuple[str, dict, str]] = []

    async def enqueue(self, name, payload=None, *, priority=None, triggered_by="manual"):
        self.enqueued.append((name, dict(payload or {}), triggered_by))
        return SimpleNamespace(id=len(self.enqueued))


async def insert_grab_history(
    db,
    *,
    download_id: str,
    series_id: int | None,
    issue_id: int | None,
    guid: str | None = "G1",
    indexer_id: int | None = 7,
    indexer_name: str | None = "DogNZB",
    title: str = "Spawn 001 (2024)",
    link: str = "https://idx.test/nzb/1",
    size_bytes: int | None = 12345,
    pub_date: dt.datetime | None = None,
    protocol: str = "usenet",
    source: str = SOURCE_INDEXER,
    client_id: int | None = 1,
) -> None:
    async with db.write_session() as session:
        session.add(
            GrabHistoryRow(
                download_id=download_id,
                client_id=client_id,
                series_id=series_id,
                issue_id=issue_id,
                indexer_id=indexer_id,
                indexer_name=indexer_name,
                guid=guid,
                title=title,
                link=link,
                size_bytes=size_bytes,
                pub_date=pub_date,
                protocol=protocol,
                source=source,
                created_at=utcnow(),
            )
        )


async def insert_tracked(
    db,
    *,
    download_id: str,
    state: TrackedDownloadState = TrackedDownloadState.DOWNLOADING,
    client_id: int | None = 1,
    client_name: str | None = "SAB",
    protocol: str = "usenet",
    series_id: int | None = None,
    issue_id: int | None = None,
    title: str | None = "Spawn 001 (2024)",
    total_size: int | None = 100,
    remaining_size: int | None = 40,
    estimated_time: int | None = 90,
    indexer_name: str | None = "DogNZB",
) -> int:
    now = utcnow()
    async with db.write_session() as session:
        row = TrackedDownloadRow(
            download_id=download_id,
            client_id=client_id,
            client_name=client_name,
            protocol=protocol,
            state=state.value,
            status="ok",
            series_id=series_id,
            issue_id=issue_id,
            title=title,
            total_size=total_size,
            remaining_size=remaining_size,
            estimated_time=estimated_time,
            indexer_name=indexer_name,
            added_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        return row.id


async def insert_blocklist(
    db,
    *,
    guid: str | None = "G1",
    indexer_id: int | None = 7,
    indexer_name: str | None = "DogNZB",
    source_title: str | None = "Spawn 001 (2024)",
    size_bytes: int | None = 12345,
    publish_date: dt.datetime | None = None,
    protocol: str | None = "usenet",
    source: str | None = SOURCE_INDEXER,
    source_url: str | None = None,
) -> None:
    async with db.write_session() as session:
        session.add(
            BlocklistRow(
                guid=guid,
                indexer_id=indexer_id,
                indexer_name=indexer_name,
                source_title=source_title,
                size_bytes=size_bytes,
                publish_date=publish_date,
                protocol=protocol,
                source=source,
                source_url=source_url,
                created_at=utcnow(),
            )
        )


async def tracked_rows(db) -> list[TrackedDownloadRow]:
    async with db.read_session() as session:
        rows = (await session.execute(select(TrackedDownloadRow))).scalars().all()
        for r in rows:
            session.expunge(r)
        return list(rows)


async def blocklist_rows(db) -> list[BlocklistRow]:
    async with db.read_session() as session:
        rows = (await session.execute(select(BlocklistRow))).scalars().all()
        for r in rows:
            session.expunge(r)
        return list(rows)


async def tracked_by_download_id(db, download_id: str) -> TrackedDownloadRow | None:
    async with db.read_session() as session:
        row = (
            await session.execute(
                select(TrackedDownloadRow).where(
                    TrackedDownloadRow.download_id == download_id
                )
            )
        ).scalars().first()
        if row is not None:
            session.expunge(row)
        return row


async def seed_library(db, tmp_path, *, issue_number: str = "1") -> tuple[int, int]:
    """Create a real root-folder + series + issue; return (series_id, issue_id)."""
    from foragerr.library import repo
    from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow

    root = tmp_path / "lib-root"
    root.mkdir(exist_ok=True)
    async with db.read_session() as session:
        profile_id = (
            await session.execute(
                select(FormatProfileRow.id).where(
                    FormatProfileRow.name == DEFAULT_PROFILE_NAME
                )
            )
        ).scalar_one()
    async with db.write_session() as session:
        rf = await repo.create_root_folder(session, str(root))
        series = await repo.create_series(
            session,
            cv_volume_id=987654,
            title="Spawn",
            start_year=2024,
            format_profile_id=profile_id,
            root_folder_id=rf.id,
            path=str(root / "Spawn"),
            monitored=True,
        )
        await session.flush()
        issue = await repo.create_issue(
            session,
            series_id=series.id,
            cv_issue_id=123456,
            issue_number=issue_number,
            cover_date=dt.date(2024, 1, 1),
            monitored=True,
        )
        await session.flush()
        return series.id, issue.id
