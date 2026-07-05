"""Shared helpers for the search-integration tests.

Builds real library rows (series / issues / files) and indexer rows in a
migrated database, and wires the search pipeline's outbound factory to an
injected recording transport that serves a stub Newznab feed — so no test
performs real DNS or network traffic. The feed's ``<item>`` titles are driven
per-test so a search returns exactly the release titles the test wants to
decide.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Callable

import httpx

from foragerr.indexers.repo import create_indexer
from foragerr.library import repo
from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow
from indexers_support import (
    IDX_BASE,
    caps_doc,
    feed_item,
    make_factory,
    newznab_feed,
    newznab_settings,
)
from sqlalchemy import select


async def make_series(
    db,
    *,
    format_profile_id: int,
    root_folder_id: int,
    title: str = "Saga",
    start_year: int | None = 2012,
    aliases: str | None = None,
    monitored: bool = True,
    path: str | None = None,
) -> int:
    """Insert a monitored series; return its id."""
    async with db.write_session() as session:
        row = await repo.create_series(
            session,
            cv_volume_id=abs(hash(title)) % 1_000_000,
            title=title,
            start_year=start_year,
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path=path or f"/library/{title.replace(' ', '_')}",
            monitored=monitored,
        )
        if aliases is not None:
            row.aliases = aliases
        return row.id


async def make_issue(
    db,
    *,
    series_id: int,
    issue_number: str = "7",
    cover_date: dt.date | None = None,
    monitored: bool = True,
    with_file: str | None = None,
) -> int:
    """Insert a monitored, released issue; return its id.

    ``cover_date`` defaults to a past date so the issue is 'wanted'.
    ``with_file`` (a filename) attaches an on-disk file so upgrade specs see it.
    """
    async with db.write_session() as session:
        issue = await repo.create_issue(
            session,
            series_id=series_id,
            cv_issue_id=abs(hash((series_id, issue_number))) % 1_000_000,
            issue_number=issue_number,
            cover_date=cover_date or dt.date(2020, 1, 1),
            monitored=monitored,
        )
        await session.flush()
        issue_id = issue.id
        if with_file is not None:
            await repo.add_issue_file(
                session, issue_id=issue_id, path=with_file, size=30_000_000
            )
        return issue_id


async def make_indexer(
    db,
    *,
    name: str = "DogNZB",
    priority: int = 10,
    enable_auto: bool = True,
    enable_interactive: bool = True,
    enable_rss: bool = True,
    enabled: bool = True,
    base_url: str = IDX_BASE,
) -> int:
    """Insert one configured newznab indexer; return its id."""
    row = await create_indexer(
        db,
        name=name,
        implementation="newznab",
        settings=newznab_settings(base_url=base_url),
        priority=priority,
        enabled=enabled,
        enable_rss=enable_rss,
        enable_auto=enable_auto,
        enable_interactive=enable_interactive,
    )
    return row.id


def feed_handler(*titles: str, guid_prefix: str = "g"):
    """A handler serving caps + a fixed set of release titles on the first page.

    Every ``t=search`` query returns the SAME items (one per title), so a test
    controls exactly which release titles the engine decides. Paging stops on
    the empty second page.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if params.get("t") == "caps":
            return httpx.Response(200, content=caps_doc())
        if int(params.get("offset", "0")) > 0:
            return httpx.Response(200, content=newznab_feed())
        items = [
            feed_item(guid=f"{guid_prefix}-{i}", title=title)
            for i, title in enumerate(titles)
        ]
        return httpx.Response(200, content=newznab_feed(*items))

    return handler


def patch_pipeline_factory(
    monkeypatch, tmp_path: Path, handler: Callable[[httpx.Request], httpx.Response]
):
    """Route the pipeline's outbound factory at a recording transport.

    Returns the recording transport so a test can inspect the requests issued.
    Patches the ``pipeline`` module attribute (the single seam both the search
    commands and the release API resolve the factory through in production).
    """
    from foragerr.search_ops import pipeline

    factory, transport = make_factory(tmp_path, handler)
    monkeypatch.setattr(pipeline, "make_indexer_factory", lambda settings: factory)
    return transport


def make_ctx(db, settings):
    """A :class:`HandlerContext` whose ``commands`` can enqueue (not started).

    Enqueue only writes a row, so the un-started service is enough to observe
    the grab hand-off; no worker pool is needed.
    """
    from foragerr.commands.service import CommandService, HandlerContext, daemon_offload

    service = CommandService(db, settings)
    return HandlerContext(
        db=db, bus=None, settings=settings, offload=daemon_offload, commands=service
    )


async def grab_rows(db) -> list:
    """Every enqueued ``grab-release`` command row (the recorded hand-offs)."""
    from foragerr.db import CommandRow

    async with db.read_session() as session:
        rows = (
            await session.execute(
                select(CommandRow).where(CommandRow.name == "grab-release")
            )
        ).scalars().all()
        return list(rows)


async def profile_id(db) -> int:
    async with db.read_session() as session:
        result = await session.execute(
            select(FormatProfileRow.id).where(
                FormatProfileRow.name == DEFAULT_PROFILE_NAME
            )
        )
        return result.scalar_one()
