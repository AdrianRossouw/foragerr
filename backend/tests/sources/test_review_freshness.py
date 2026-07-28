"""Review-proposal freshness + failed-download retry (FRG-SRC-008, FRG-SRC-009).

The library moves underneath a review list, and store downloads fail. These
cover the two trust repairs from the live-rig findings:

* **FRG-SRC-008** — an add whose volume is already in the library degrades to a
  match instead of 400-ing, and a successful add re-resolves the sibling
  entitlements whose proposals named the same volume (operator decisions are
  never overwritten).
* **FRG-SRC-009** — an explicit retry re-queues a failed download through the
  standard grab seam, and failed downloads degrade health aggregated per source.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from foragerr.db.base import utcnow
from foragerr.downloads.models import TrackedDownloadRow
from foragerr.downloads.state import TrackedDownloadState
from foragerr.health.service import HealthService
from foragerr.library import repo as library_repo
from foragerr.library.flows._common import SeriesValidationError
from foragerr.library.models import SeriesRow
from foragerr.sources import ratelimit, repo, review
from foragerr.sources.grab import _handoff_to_import
from foragerr.sources.models import SourceEntitlementRow
from foragerr.sources.registry import TYPE_HUMBLE
from foragerr.sources.service import run_sync
from foragerr.sources.settings import HumbleSettings
from flows_support import FakeCV, build_factory, flows_settings, reset_gate
from http_support import make_settings
from sources_support import (  # noqa: F401 — imported fixtures
    fixture_bytes,
    format_profile_id,
    make_factory,
    order_handler,
    root_folder_id,
)

GAMEKEY = "aBcD1234synthetic"


@pytest.fixture(autouse=True)
def _reset_gates():
    ratelimit.reset_gates()
    reset_gate()
    yield
    ratelimit.reset_gates()
    reset_gate()


class FakeCommands:
    """Records enqueued commands (the grab / refresh hand-offs)."""

    def __init__(self):
        self.enqueued: list[tuple] = []

    async def enqueue(self, name, payload=None, *, triggered_by="manual"):
        self.enqueued.append((name, payload, triggered_by))
        return SimpleNamespace(id=len(self.enqueued), status="queued")

    def grabs(self) -> list[tuple]:
        return [c for c in self.enqueued if c[0] == "source-grab"]


async def _synced_source(db, config_dir, *, auto_sync=False):
    source = await repo.create_source(
        db,
        source_type=TYPE_HUMBLE,
        name="Humble Bundle",
        settings=HumbleSettings(session_cookie="SYNTH-COOKIE"),
        auto_sync=auto_sync,
        connection_state="connected",
    )
    handler = order_handler(
        list_body=b'[{"gamekey":"%s"}]' % GAMEKEY.encode(),
        order_bodies={GAMEKEY: fixture_bytes("order_comics.json")},
    )
    factory = make_factory(config_dir, httpx.MockTransport(handler))
    await run_sync(db, factory, source, min_interval=0.0)
    return source


async def _comic(db, source_id, machine_name) -> SourceEntitlementRow:
    for e in await repo.list_entitlements(db, source_id, classification="comic"):
        if e.machine_name == machine_name:
            return e
    raise AssertionError(f"no entitlement {machine_name}")


async def _mk_series(db, root_folder_id, format_profile_id, *, cvid, title):
    async with db.write_session() as session:
        series = await library_repo.create_series(
            session,
            cv_volume_id=cvid,
            title=title,
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path=f"/tmp/comics/{title} ({cvid})",
        )
        return series.id


def _cv_proposal(cvid: int, *, title: str = "Synthetic Hero") -> str:
    """A stored ComicVine-kind proposal (the shape ``ProposedMatch.to_json``
    writes) naming ``cvid`` — i.e. an ADD suggestion."""
    return json.dumps(
        {
            "kind": "comicvine",
            "series_id": None,
            "cv_volume_id": cvid,
            "title": title,
            "year": 2019,
            "confidence": 0.71,
            "auto": False,
            "candidates": [
                {
                    "kind": "comicvine",
                    "series_id": None,
                    "cv_volume_id": cvid,
                    "title": title,
                    "year": 2019,
                    "confidence": 0.71,
                },
                {
                    "kind": "comicvine",
                    "series_id": None,
                    "cv_volume_id": cvid + 1,
                    "title": f"{title} Annual",
                    "year": 2020,
                    "confidence": 0.55,
                },
            ],
        },
        sort_keys=True,
    )


async def _set_proposal(db, entitlement_id: int, payload: str) -> None:
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, entitlement_id)
        row.proposed_match_json = payload
        row.proposed_series_id = None
        row.updated_at = utcnow()


async def _mark_failed(db, entitlement_id: int, *, error: str = "checksum mismatch"):
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, entitlement_id)
        row.review_status = "matched"
        row.download_state = "failed"
        row.download_error = error
        row.updated_at = utcnow()


async def _handoff(db, entitlement_id: int, path) -> None:
    """Run the grab's REAL import handoff (dedup included) for an entitlement."""
    ent = await repo.get_entitlement(db, entitlement_id)
    await _handoff_to_import(db, ent, path)


async def _tracked(db, entitlement_id: int) -> TrackedDownloadRow | None:
    async with db.read_session() as session:
        row = (
            (
                await session.execute(
                    select(TrackedDownloadRow).where(
                        TrackedDownloadRow.download_id == f"humble:{entitlement_id}"
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is not None:
            session.expunge(row)
        return row


async def _set_tracked_state(db, entitlement_id: int, state: TrackedDownloadState):
    async with db.write_session() as session:
        row = (
            (
                await session.execute(
                    select(TrackedDownloadRow).where(
                        TrackedDownloadRow.download_id == f"humble:{entitlement_id}"
                    )
                )
            )
            .scalars()
            .one()
        )
        row.state = state.value


# --- FRG-SRC-008: add degrades to match -------------------------------------


@pytest.mark.req("FRG-SRC-008")
async def test_add_on_in_library_volume_degrades_to_match(
    db, config_dir, root_folder_id, format_profile_id
):
    """The proposed volume is already a library series (an earlier add, or a
    manual one): the add matches it instead of failing, with the match action's
    outcome — link + accept + grab queued. ``add_series`` is never reached (no
    ComicVine factory is supplied, so a call would blow up)."""
    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=880, title="Synthetic Hero"
    )
    ent = await _comic(db, source.id, "synth_singleissue_01")
    await _set_proposal(db, ent.id, _cv_proposal(880))
    commands = FakeCommands()

    row = await review.add_entitlement(
        db, make_settings(config_dir), ent.id, commands=commands
    )

    assert row.review_status == "matched"
    assert row.matched_series_id == series_id
    # The degrade is an operator action like any other match (FRG-PP-022 guard 3).
    assert row.matched_via == "operator"
    assert row.download_state == "queued"
    assert commands.grabs() == [("source-grab", {"entitlement_id": ent.id}, "accept")]


@pytest.mark.req("FRG-SRC-008")
async def test_add_with_explicit_in_library_cv_id_degrades_to_match(
    db, config_dir, root_folder_id, format_profile_id
):
    """The degrade also covers an explicitly supplied ``cv_volume_id`` (the
    operator picked the volume by hand), not just the stored proposal."""
    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=881, title="Synthetic Hero"
    )
    ent = await _comic(db, source.id, "synth_collected_edition_vol1")

    row = await review.add_entitlement(
        db,
        make_settings(config_dir),
        ent.id,
        commands=FakeCommands(),
        cv_volume_id=881,
    )
    assert row.review_status == "matched"
    assert row.matched_series_id == series_id


@pytest.mark.req("FRG-SRC-008")
async def test_genuine_add_failure_still_surfaces_as_400(
    db, config_dir, root_folder_id
):
    """Narrowing the catch-all must not swallow a REAL add failure: a volume
    ComicVine does not serve still raises the 400-mapped action error."""
    source = await _synced_source(db, config_dir)
    settings = flows_settings(config_dir)
    factory = build_factory(settings, FakeCV().handler())  # no volume registered
    ent = await _comic(db, source.id, "synth_singleissue_01")
    await _set_proposal(db, ent.id, _cv_proposal(4242))

    with pytest.raises(review.EntitlementActionError) as exc:
        await review.add_entitlement(
            db, settings, ent.id, commands=FakeCommands(), factory=factory
        )
    assert exc.value.status == 400
    after = await repo.get_entitlement(db, ent.id)
    assert after.review_status == "new"
    assert after.matched_series_id is None


@pytest.mark.req("FRG-SRC-008")
async def test_add_losing_a_concurrent_race_degrades_instead_of_400(
    db, config_dir, root_folder_id, format_profile_id, monkeypatch
):
    """The presence pre-check and the add are separate transactions, so two
    near-simultaneous adds of the same volume both pass the pre-check and the
    loser's ``add_series`` rejects it as already in the library. That rejection
    must land on the degrade path, not on the generic 400 FRG-SRC-008 removes."""
    source = await _synced_source(db, config_dir)
    ent = await _comic(db, source.id, "synth_singleissue_01")
    await _set_proposal(db, ent.id, _cv_proposal(884))
    created: dict[str, int] = {}

    async def _racing_add(*args, **kwargs):
        # The "other" add commits the volume, then ours rejects — the loser.
        created["id"] = await _mk_series(
            db, root_folder_id, format_profile_id, cvid=884, title="Synthetic Hero"
        )
        raise SeriesValidationError("volume 884 is already in the library")

    monkeypatch.setattr("foragerr.library.flows.add.add_series", _racing_add)
    commands = FakeCommands()

    row = await review.add_entitlement(
        db, make_settings(config_dir), ent.id, commands=commands
    )

    assert row.review_status == "matched"
    assert row.matched_series_id == created["id"]
    assert row.download_state == "queued"
    assert commands.grabs() == [("source-grab", {"entitlement_id": ent.id}, "accept")]


# --- FRG-SRC-008: sibling re-resolution -------------------------------------


@pytest.mark.req("FRG-SRC-008")
async def test_degrade_to_match_also_reresolves_siblings(
    db, config_dir, root_folder_id, format_profile_id
):
    """The sweep's intent is first-click-correct SIBLINGS, so it must run on the
    degrade path too — not only after a real add. Without it each sibling would
    degrade individually, i.e. only after another click apiece."""
    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=885, title="Synthetic Hero"
    )
    acting = await _comic(db, source.id, "synth_singleissue_01")
    sibling = await _comic(db, source.id, "synth_collected_edition_vol1")
    for eid in (acting.id, sibling.id):
        await _set_proposal(db, eid, _cv_proposal(885))

    await review.add_entitlement(
        db, make_settings(config_dir), acting.id, commands=FakeCommands()
    )

    after = await repo.get_entitlement(db, sibling.id)
    assert after.review_status == "new"  # still the operator's to decide
    assert after.proposed_series_id == series_id
    proposal = json.loads(after.proposed_match_json)
    assert proposal["kind"] == "library"
    assert proposal["series_id"] == series_id
    assert proposal["auto"] is False
    assert len(proposal["candidates"]) == 2  # ranked alternatives preserved


@pytest.mark.req("FRG-SRC-008")
async def test_successful_add_reresolves_sibling_proposals(
    db, config_dir, root_folder_id, format_profile_id
):
    """Siblings proposing the SAME volume become library-kind match proposals
    against the created series, so their next single action succeeds first
    click — while matched / ignored rows keep exactly what the operator set."""
    source = await _synced_source(db, config_dir)
    settings = flows_settings(config_dir)
    factory = build_factory(
        settings, FakeCV().volume(990, name="Synthetic Hero").handler()
    )

    acting = await _comic(db, source.id, "synth_singleissue_01")
    sibling = await _comic(db, source.id, "synth_collected_edition_vol1")
    decided = [
        e
        for e in await repo.list_entitlements(db, source.id, classification="comic")
        if e.id not in {acting.id, sibling.id}
    ][0]
    for eid in (acting.id, sibling.id, decided.id):
        await _set_proposal(db, eid, _cv_proposal(990))
    # An operator decision on the third row: ignored, with the same proposal.
    await review.ignore_entitlement(db, decided.id)
    await _set_proposal(db, decided.id, _cv_proposal(990))
    untouched_before = (await repo.get_entitlement(db, decided.id)).proposed_match_json

    commands = FakeCommands()
    added = await review.add_entitlement(
        db, settings, acting.id, commands=commands, factory=factory
    )
    assert added.review_status == "matched"
    new_series_id = added.matched_series_id
    async with db.read_session() as session:
        created = await session.get(SeriesRow, new_series_id)
    assert created.cv_volume_id == 990

    # The sibling now proposes a MATCH against the created series.
    after = await repo.get_entitlement(db, sibling.id)
    assert after.review_status == "new"  # still the operator's to decide
    assert after.proposed_series_id == new_series_id
    proposal = json.loads(after.proposed_match_json)
    assert proposal["kind"] == "library"
    assert proposal["series_id"] == new_series_id
    assert proposal["auto"] is False  # a rewrite never licenses auto-accept
    assert len(proposal["candidates"]) == 2  # ranked alternatives preserved

    # ...and that next single action succeeds on the first click.
    matched = await review.match_entitlement(
        db, sibling.id, series_id=after.proposed_series_id, commands=commands
    )
    assert matched.review_status == "matched"
    assert matched.matched_series_id == new_series_id


@pytest.mark.req("FRG-SRC-008")
async def test_sweep_leaves_matched_and_ignored_rows_untouched(
    db, config_dir, root_folder_id, format_profile_id
):
    """Only ``new`` rows are re-resolved — a matched or ignored entitlement is an
    operator decision the sweep must never overwrite."""
    source = await _synced_source(db, config_dir)
    settings = flows_settings(config_dir)
    factory = build_factory(
        settings, FakeCV().volume(991, name="Synthetic Hero").handler()
    )
    other_series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=101, title="Other Series"
    )

    comics = await repo.list_entitlements(db, source.id, classification="comic")
    acting, matched_row, ignored_row = comics[0], comics[1], comics[2]
    for e in comics:
        await _set_proposal(db, e.id, _cv_proposal(991))
    await review.match_entitlement(
        db, matched_row.id, series_id=other_series_id, commands=FakeCommands()
    )
    await review.ignore_entitlement(db, ignored_row.id)
    await _set_proposal(db, matched_row.id, _cv_proposal(991))
    await _set_proposal(db, ignored_row.id, _cv_proposal(991))
    frozen = _cv_proposal(991)

    await review.add_entitlement(
        db, settings, acting.id, commands=FakeCommands(), factory=factory
    )

    still_matched = await repo.get_entitlement(db, matched_row.id)
    still_ignored = await repo.get_entitlement(db, ignored_row.id)
    assert still_matched.review_status == "matched"
    assert still_matched.matched_series_id == other_series_id
    assert still_matched.proposed_match_json == frozen
    assert still_matched.proposed_series_id is None
    assert still_ignored.review_status == "ignored"
    assert still_ignored.proposed_match_json == frozen
    assert still_ignored.proposed_series_id is None


# --- FRG-SRC-009: retry ------------------------------------------------------


@pytest.mark.req("FRG-SRC-009")
async def test_retry_requeues_a_failed_download(
    db, config_dir, root_folder_id, format_profile_id
):
    """Retry clears the recorded failure and re-queues through the standard grab
    task — the download state reflects the new attempt."""
    source = await _synced_source(db, config_dir)
    ent = await _comic(db, source.id, "synth_singleissue_01")
    await _mark_failed(db, ent.id, error="md5 mismatch on the downloaded file")
    commands = FakeCommands()

    row = await review.retry_download(db, ent.id, commands=commands)

    assert row.download_state == "queued"
    assert row.download_error is None
    assert commands.grabs() == [("source-grab", {"entitlement_id": ent.id}, "accept")]


@pytest.mark.req("FRG-SRC-009")
async def test_retry_without_a_grabbable_copy_is_a_conflict(
    db, config_dir, root_folder_id, format_profile_id
):
    """A failed entitlement whose preferred copy vanished on a later re-sync
    (md5/filename overwritten to nothing) 409s instead of silently no-opping —
    a retry must never pretend to queue a download it cannot perform."""
    source = await _synced_source(db, config_dir)
    ent = await _comic(db, source.id, "synth_singleissue_01")
    await _mark_failed(db, ent.id, error="md5 mismatch on the downloaded file")
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, ent.id)
        row.md5 = None
        row.filename = None
    commands = FakeCommands()

    with pytest.raises(review.EntitlementActionError) as exc:
        await review.retry_download(db, ent.id, commands=commands)
    assert exc.value.status == 409
    assert "no downloadable copy" in str(exc.value)
    assert commands.enqueued == []
    after = await repo.get_entitlement(db, ent.id)
    assert after.download_state == "failed"  # untouched


@pytest.mark.req("FRG-SRC-009")
async def test_retry_on_a_non_failed_download_is_a_conflict(
    db, config_dir, root_folder_id, format_profile_id
):
    """Retry is failed-only: any other download state is a 409 with no change
    (and never a second grab)."""
    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=882, title="Synthetic Hero"
    )
    ent = await _comic(db, source.id, "synth_singleissue_01")
    await review.match_entitlement(
        db, ent.id, series_id=series_id, commands=FakeCommands()
    )
    commands = FakeCommands()

    with pytest.raises(review.EntitlementActionError) as exc:
        await review.retry_download(db, ent.id, commands=commands)
    assert exc.value.status == 409
    assert commands.enqueued == []
    after = await repo.get_entitlement(db, ent.id)
    assert after.download_state == "queued"  # untouched
    assert after.review_status == "matched"


@pytest.mark.req("FRG-SRC-009")
async def test_retry_after_an_import_failure_clears_the_wedging_tracked_row(
    db, config_dir, root_folder_id, format_profile_id, tmp_path
):
    """``download_state = "failed"`` also covers an IMPORT-level failure, where the
    ``humble:{id}`` tracked row SURVIVES as ``failed_pending``. The handoff dedups
    on download id regardless of state, so retrying without clearing that row
    would re-download into a no-op handoff and wedge the entitlement at
    ``import_pending`` forever. The stale row is deleted, so the re-grab's handoff
    lands a fresh, claimable one."""
    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=886, title="Synthetic Hero"
    )
    ent = await _comic(db, source.id, "synth_singleissue_01")
    await review.match_entitlement(
        db, ent.id, series_id=series_id, commands=FakeCommands()
    )
    # The grab handed off; the drain then FAILED the import — apply_source_import
    # mirrors "failed" onto the entitlement while the tracked row lives on.
    await _handoff(db, ent.id, tmp_path / "attempt-1.cbz")
    await _set_tracked_state(db, ent.id, TrackedDownloadState.FAILED_PENDING)
    await _mark_failed(db, ent.id, error="import failed — archive rejected")

    commands = FakeCommands()
    row = await review.retry_download(db, ent.id, commands=commands)

    assert row.download_state == "queued"
    assert row.download_error is None
    assert await _tracked(db, ent.id) is None  # the wedging row is gone
    assert commands.grabs() == [("source-grab", {"entitlement_id": ent.id}, "accept")]

    # ...so the re-grab's handoff writes a FRESH import_pending row rather than
    # silently deduping into nothing. (SQLite reuses rowids, so the NEW attempt's
    # output path — not the row id — is what proves the row was rewritten.)
    second = tmp_path / "attempt-2.cbz"
    await _handoff(db, ent.id, second)
    fresh = await _tracked(db, ent.id)
    assert fresh.state == TrackedDownloadState.IMPORT_PENDING.value
    assert fresh.output_path == str(second)


@pytest.mark.req("FRG-SRC-009")
async def test_retry_while_the_import_is_claimed_is_a_conflict(
    db, config_dir, root_folder_id, format_profile_id, tmp_path
):
    """The drain-claimed ``importing`` row is the one carve-out: deleting it would
    strand an in-flight move, so the retry is refused (409) and the row stands."""
    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=887, title="Synthetic Hero"
    )
    ent = await _comic(db, source.id, "synth_singleissue_01")
    await review.match_entitlement(
        db, ent.id, series_id=series_id, commands=FakeCommands()
    )
    await _handoff(db, ent.id, tmp_path / "attempt-1.cbz")
    await _set_tracked_state(db, ent.id, TrackedDownloadState.IMPORTING)
    await _mark_failed(db, ent.id)
    commands = FakeCommands()

    with pytest.raises(review.EntitlementActionError) as exc:
        await review.retry_download(db, ent.id, commands=commands)

    assert exc.value.status == 409
    assert commands.enqueued == []
    still = await _tracked(db, ent.id)
    assert still is not None
    assert still.state == TrackedDownloadState.IMPORTING.value
    after = await repo.get_entitlement(db, ent.id)
    assert after.download_state == "failed"  # untouched


@pytest.mark.req("FRG-SRC-009")
async def test_retry_on_an_unknown_entitlement_is_404(db):
    with pytest.raises(review.EntitlementActionError) as exc:
        await review.retry_download(db, 999999, commands=FakeCommands())
    assert exc.value.status == 404


# --- FRG-SRC-009: health -----------------------------------------------------


@pytest.mark.req("FRG-SRC-009")
async def test_failed_downloads_degrade_health_aggregated_per_source(
    db, config_dir, tmp_path
):
    """N failed downloads on one source produce ONE degraded component carrying
    the count (never one per row), and it clears once none remain failed."""
    source = await _synced_source(db, config_dir)
    comics = await repo.list_entitlements(db, source.id, classification="comic")
    for e in comics[:2]:
        await _mark_failed(db, e.id)

    service = HealthService(db, make_settings(tmp_path))
    warnings = [
        w
        for w in await service.warnings()
        if w.source.startswith("source-downloads:")
    ]
    assert len(warnings) == 1  # aggregated per source, not per entitlement
    assert "2 failed download(s)" in warnings[0].message
    assert "Humble Bundle" in warnings[0].message
    assert "retry" in (warnings[0].remediation_hint or "").lower()

    components = [
        c
        for c in await service.component_view()
        if c.component.startswith("source-downloads:")
    ]
    assert [c.state for c in components] == ["degraded"]
    assert components[0].last_failure is not None

    # Clearing the failures (a retry re-queues) removes the component entirely.
    for e in comics[:2]:
        await review.retry_download(db, e.id, commands=FakeCommands())
    assert not [
        c
        for c in await service.component_view()
        if c.component.startswith("source-downloads:")
    ]


@pytest.mark.req("FRG-SRC-009")
async def test_no_failed_downloads_is_not_a_health_warning(db, config_dir, tmp_path):
    await _synced_source(db, config_dir)
    service = HealthService(db, make_settings(tmp_path))
    assert not [
        w
        for w in await service.warnings()
        if w.source.startswith("source-downloads:")
    ]
