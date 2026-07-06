"""Add-flow validation + persistence + chain enqueue (FRG-SER-005, FRG-SER-001)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from foragerr.commands import CommandService
from foragerr.db import CommandRow
from foragerr.library import repo
from foragerr.library.flows import (
    AddSeriesResult,
    SeriesValidationError,
    add_series,
    decode_add_options,
)
from foragerr.library.models import SeriesRow

from flows_support import FakeCV, build_factory, flows_settings, issue


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return flows_settings(cfg)


@pytest.fixture
async def commands(db, settings, command_registry):
    return CommandService(db, settings)


async def _count(db, model) -> int:
    async with db.read_session() as session:
        return await session.scalar(select(func.count()).select_from(model))


@pytest.mark.req("FRG-SER-005")
async def test_add_rejects_nonexistent_cv_volume(
    db, settings, commands, root_folder_id
):
    factory = build_factory(settings, FakeCV().handler())  # no volume registered
    with pytest.raises(SeriesValidationError):
        await add_series(
            db,
            settings,
            cv_volume_id=999,
            root_folder_id=root_folder_id,
            commands=commands,
            factory=factory,
        )
    assert await _count(db, SeriesRow) == 0
    assert await _count(db, CommandRow) == 0


@pytest.mark.req("FRG-SER-005")
async def test_add_auth_failure_surfaces_credential_message(
    db, settings, commands, root_folder_id
):
    """A ComicVine auth rejection on the existence check surfaces the same
    actionable credential wording as the lookup endpoint (add-flow parity,
    m2-lookup-error-surfacing) — static text, never the key value."""
    import httpx

    factory = build_factory(
        settings, lambda _request: httpx.Response(401, content=b"unauthorized")
    )
    with pytest.raises(SeriesValidationError) as excinfo:
        await add_series(
            db,
            settings,
            cv_volume_id=42,
            root_folder_id=root_folder_id,
            commands=commands,
            factory=factory,
        )
    from foragerr.metadata import COMICVINE_CREDENTIAL_MESSAGE

    assert str(excinfo.value) == (
        f"comicvine volume 42 could not be fetched: {COMICVINE_CREDENTIAL_MESSAGE}"
    )
    # The shared constant itself stays the exact byte-identical sentence the
    # frontend keys its credential classification on.
    assert COMICVINE_CREDENTIAL_MESSAGE == (
        "ComicVine rejected the API key (missing or invalid) "
        "\u2014 set comicvine_api_key"
    )
    # the key value (flows_settings default) never leaks into the message
    assert "CV-SECRET-KEY-abc123" not in str(excinfo.value)
    assert await _count(db, SeriesRow) == 0
    assert await _count(db, CommandRow) == 0


@pytest.mark.req("FRG-SER-005")
async def test_add_rejects_unregistered_root_folder(db, settings, commands):
    factory = build_factory(settings, FakeCV().volume(42).handler())
    with pytest.raises(SeriesValidationError):
        await add_series(
            db,
            settings,
            cv_volume_id=42,
            root_folder_id=4242,  # not registered
            commands=commands,
            factory=factory,
        )
    assert await _count(db, SeriesRow) == 0
    assert await _count(db, CommandRow) == 0


@pytest.mark.req("FRG-SER-005")
async def test_add_rejects_duplicate_cv_volume(
    db, settings, commands, root_folder_id
):
    factory = build_factory(settings, FakeCV().volume(42, name="Saga").handler())
    await add_series(
        db, settings, cv_volume_id=42, root_folder_id=root_folder_id,
        commands=commands, factory=factory,
    )
    with pytest.raises(SeriesValidationError):
        await add_series(
            db, settings, cv_volume_id=42, root_folder_id=root_folder_id,
            commands=commands, factory=factory,
        )
    async with db.read_session() as session:
        rows = (await session.execute(select(SeriesRow))).scalars().all()
    assert len(rows) == 1


@pytest.mark.req("FRG-SER-005")
async def test_successful_add_persists_and_enqueues_refresh(
    db, settings, commands, root_folder_id
):
    factory = build_factory(
        settings,
        FakeCV().volume(42, name="Saga", publisher="Image", start_year=2012).handler(),
    )
    result = await add_series(
        db,
        settings,
        cv_volume_id=42,
        root_folder_id=root_folder_id,
        commands=commands,
        monitor_strategy="first",
        monitor_new_items="none",
        search_on_add=True,
        factory=factory,
    )
    assert isinstance(result, AddSeriesResult)

    async with db.read_session() as session:
        series = await repo.get_series(session, result.series.id)
    assert series.cv_volume_id == 42
    assert series.title == "Saga"
    assert series.publisher == "Image"
    assert series.monitor_new_items == "none"
    assert series.path.endswith("Saga (2012)")
    opts = decode_add_options(series.add_options)
    assert opts.monitor_strategy == "first"
    assert opts.search_on_add is True

    # The refresh command is on the persisted backbone, keyed to this series.
    record = await commands.get(result.refresh_command_id)
    assert record is not None
    assert record.name == "refresh-series"
    assert record.payload == {"series_id": series.id}


@pytest.mark.req("FRG-SER-001")
async def test_add_without_profile_uses_seeded_default(
    db, settings, commands, root_folder_id, format_profile_id
):
    factory = build_factory(settings, FakeCV().volume(7, name="Paper Girls").handler())
    result = await add_series(
        db, settings, cv_volume_id=7, root_folder_id=root_folder_id,
        commands=commands, factory=factory,
    )
    async with db.read_session() as session:
        series = await repo.get_series(session, result.series.id)
    assert series.format_profile_id == format_profile_id


@pytest.mark.req("FRG-SER-005")
async def test_add_rejects_colliding_computed_path(
    db, settings, commands, root_folder_id
):
    """Two volumes whose default path collides (same title+year) must reject
    cleanly (SeriesValidationError -> 400), not raise a raw IntegrityError."""
    factory = build_factory(
        settings,
        FakeCV()
        .volume(11, name="Bone", start_year=1991)
        .volume(12, name="Bone", start_year=1991)
        .handler(),
    )
    await add_series(
        db, settings, cv_volume_id=11, root_folder_id=root_folder_id,
        commands=commands, factory=factory,
    )
    with pytest.raises(SeriesValidationError):
        await add_series(
            db, settings, cv_volume_id=12, root_folder_id=root_folder_id,
            commands=commands, factory=factory,
        )
    async with db.read_session() as session:
        rows = (await session.execute(select(SeriesRow))).scalars().all()
    assert len(rows) == 1


@pytest.mark.req("FRG-SER-008")
async def test_path_override_must_be_under_root(
    db, settings, commands, root_folder_id, root_folder_path, tmp_path
):
    factory = build_factory(settings, FakeCV().volume(9, name="Nimona").handler())
    # under-root override is accepted
    good = root_folder_path / "Custom Nimona"
    result = await add_series(
        db, settings, cv_volume_id=9, root_folder_id=root_folder_id,
        commands=commands, path_override=str(good), factory=factory,
    )
    async with db.read_session() as session:
        series = await repo.get_series(session, result.series.id)
    assert Path(series.path) == good.resolve()

    # outside-root override is rejected with no row
    factory2 = build_factory(settings, FakeCV().volume(10, name="Bone").handler())
    outside = tmp_path / "elsewhere" / "Bone"
    with pytest.raises(SeriesValidationError):
        await add_series(
            db, settings, cv_volume_id=10, root_folder_id=root_folder_id,
            commands=commands, path_override=str(outside), factory=factory2,
        )
    async with db.read_session() as session:
        remaining = (await session.execute(select(SeriesRow.cv_volume_id))).scalars().all()
    assert 10 not in remaining
