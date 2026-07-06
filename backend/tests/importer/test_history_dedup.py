"""FRG-API-011 — RISK-040 dedup at the writer seam (m2-daily-surfaces design
decision 2): an identical repeated blocked/failed outcome for one download
never accretes another history row, while any payload change — and the
retry-on-evidence loop itself — is untouched."""

from __future__ import annotations

from pathlib import Path

import pytest

from foragerr.importer import history
from foragerr.importer.pipeline import ImportStatus, gather, import_candidate
from foragerr.importer.sources import CompletedDownloadSource

from importer._archives import make_cbz


async def _all_events(db):
    async with db.read_session() as session:
        rows = await history.all_events(session)
        for r in rows:
            session.expunge(r)
        return rows


async def _run(db, source, ctx):
    outcomes = []
    async with db.write_session() as session:
        for candidate in await gather(source, session, ctx):
            outcomes.append(await import_candidate(session, candidate, ctx))
    return outcomes


# --- the real retry path -----------------------------------------------------


@pytest.mark.req("FRG-API-011")
async def test_identical_blocked_retries_accrete_exactly_one_row(
    db, seed, import_ctx
):
    """The tracking loop re-feeds a still-completed blocked download every
    cycle; re-running the pipeline over the unchanged download N times must
    leave exactly ONE import_blocked row (RISK-040) — and still BLOCK each
    time (the retry loop itself is untouched)."""
    await seed()
    ctx = import_ctx()
    dl_dir = Path(ctx.config_dir).parent / "dl-dedup"
    make_cbz(dl_dir / "Totally Unknown Series 001 (2099).cbz")
    source = CompletedDownloadSource(download_id="dup-1", output_path=str(dl_dir))

    for _ in range(3):  # three tracking cycles re-feed the identical item
        outcomes = await _run(db, source, ctx)
        assert [o.status for o in outcomes] == [ImportStatus.BLOCKED]

    events = await _all_events(db)
    blocked = [e for e in events if e.event_type == history.EVENT_IMPORT_BLOCKED]
    assert len(blocked) == 1  # N identical retries -> one row
    assert blocked[0].download_id == "dup-1"


# --- writer-seam semantics ----------------------------------------------------


def _blocked_kwargs(**overrides):
    kwargs = dict(
        event_type=history.EVENT_IMPORT_BLOCKED,
        download_id="d1",
        source_title="Spawn 001",
        source=history.SOURCE_DOWNLOAD,
        data={"reasons": ["no free space"], "source_kind": "download"},
    )
    kwargs.update(overrides)
    return kwargs


@pytest.mark.req("FRG-API-011")
async def test_changed_reasons_write_a_second_row(db):
    async with db.write_session() as session:
        first = await history.record_event_deduped(session, **_blocked_kwargs())
        assert first is not None
    async with db.write_session() as session:
        skipped = await history.record_event_deduped(session, **_blocked_kwargs())
        assert skipped is None  # byte-identical repeat -> suppressed
    async with db.write_session() as session:
        changed = await history.record_event_deduped(
            session,
            **_blocked_kwargs(
                data={"reasons": ["quality below cutoff"], "source_kind": "download"}
            ),
        )
        assert changed is not None  # ANY payload change writes
    events = await _all_events(db)
    assert len(events) == 2


@pytest.mark.req("FRG-API-011")
async def test_event_type_flip_for_the_same_download_writes(db):
    """blocked -> failed for one download is a NEW outcome, never suppressed
    even when the data payload happens to be identical."""
    data = {"reasons": ["bad archive"], "source_kind": "download"}
    async with db.write_session() as session:
        await history.record_event_deduped(session, **_blocked_kwargs(data=data))
    async with db.write_session() as session:
        flipped = await history.record_event_deduped(
            session,
            **_blocked_kwargs(event_type=history.EVENT_IMPORT_FAILED, data=data),
        )
        assert flipped is not None
    assert len(await _all_events(db)) == 2


@pytest.mark.req("FRG-API-011")
async def test_events_without_a_download_id_are_never_deduped(db):
    """Rescan-shaped blocked events carry no download_id — the dedup key does
    not exist, so identical payloads all write (unchanged M1 behavior)."""
    for _ in range(2):
        async with db.write_session() as session:
            row = await history.record_event_deduped(
                session, **_blocked_kwargs(download_id=None)
            )
            assert row is not None
    assert len(await _all_events(db)) == 2


@pytest.mark.req("FRG-API-011")
async def test_non_blocked_event_types_are_never_deduped(db):
    """Only import_blocked/import_failed are retry-fed; every other event type
    passes straight through even with identical payloads."""
    for _ in range(2):
        async with db.write_session() as session:
            row = await history.record_event_deduped(
                session,
                event_type=history.EVENT_IMPORTED,
                download_id="d1",
                source_title="Spawn 001",
                source=history.SOURCE_DOWNLOAD,
                data={"size": 1},
            )
            assert row is not None
    assert len(await _all_events(db)) == 2
