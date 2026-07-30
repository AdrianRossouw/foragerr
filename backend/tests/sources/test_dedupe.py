"""md5-identical entitlement dedupe (FRG-SRC-015) and the review states it
extends (FRG-SRC-004).

The shape under test is the store selling one file in two bundles: two
entitlements with two store-native keys and ONE md5, which reviewed as two rows
and downloaded the same bytes twice. Linking parks the later row behind the
earlier one so the set reviews, counts and downloads exactly once.
"""

from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from foragerr.sources import ratelimit, repo, review
from foragerr.sources.dedupe import (
    duplicate_backfill_startup_hook,
    link_duplicate_entitlements,
)
from foragerr.sources.models import MATCHED_VIA_OPERATOR, SourceEntitlementRow
from foragerr.sources.registry import TYPE_HUMBLE
from foragerr.sources.service import run_sync
from foragerr.sources.settings import HumbleSettings
from sources_support import (  # noqa: F401 — imported fixtures
    FakeCommands,
    _mk_series,
    format_profile_id,
    make_factory,
    order_handler,
    root_folder_id,
)

#: The one file two bundles sell. A synthetic 32-hex digest: the store computes
#: the real one from the file bytes, and equality of THAT is the whole signal.
SHARED_MD5 = "0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f"
OTHER_MD5 = "1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a"
#: A third file, so a "different bytes" case cannot accidentally collide with
#: either of the two above.
THIRD_MD5 = "2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b"

FIRST_KEY = "gamekey-first-bundle"
SECOND_KEY = "gamekey-second-bundle"


@pytest.fixture(autouse=True)
def _reset_gates():
    ratelimit.reset_gates()
    yield
    ratelimit.reset_gates()


def _order(gamekey: str, bundle: str, items: list[tuple[str, str, str | None]]) -> bytes:
    """One synthetic Humble order body. Each item is
    ``(machine_name, human_name, md5)``; a ``None`` md5 is the store omitting the
    digest, which must never be treated as identity."""
    return json.dumps(
        {
            "gamekey": gamekey,
            "product": {"machine_name": bundle.lower(), "human_name": bundle},
            "subproducts": [
                {
                    "machine_name": machine_name,
                    "human_name": human_name,
                    "publisher": "Example Comics",
                    "downloads": [
                        {
                            "platform": "ebook",
                            "download_struct": [
                                {
                                    "name": "CBZ",
                                    "md5": md5,
                                    "file_size": 1024,
                                    "url": {
                                        "web": f"https://example.com/{machine_name}.cbz"
                                    },
                                }
                            ],
                        }
                    ],
                }
                for machine_name, human_name, md5 in items
            ],
        }
    ).encode()


async def _twin_source(db, config_dir, *, second_md5: str | None = SHARED_MD5):
    """A connected source synced over two bundles that share one file.

    ``second_md5`` lets a test serve a DIFFERENT (or absent) digest for the
    second bundle's copy without changing anything else about the shape.
    """
    source = await repo.create_source(
        db,
        source_type=TYPE_HUMBLE,
        name="Example Store",
        settings=HumbleSettings(session_cookie="SYNTH-COOKIE"),
    )
    handler = order_handler(
        list_body=json.dumps(
            [{"gamekey": FIRST_KEY}, {"gamekey": SECOND_KEY}]
        ).encode(),
        order_bodies={
            FIRST_KEY: _order(
                FIRST_KEY,
                "Example First Bundle",
                [
                    ("first_saga_v1", "Example Saga Vol. 1", SHARED_MD5),
                    ("first_other", "Example Other Title #1", OTHER_MD5),
                ],
            ),
            SECOND_KEY: _order(
                SECOND_KEY,
                "Example Second Bundle",
                [("second_saga_v1", "Example Saga Vol. 1", second_md5)],
            ),
        },
    )
    factory = make_factory(config_dir, httpx.MockTransport(handler))
    result = await run_sync(db, factory, source, min_interval=0.0)
    return source, result


async def _by_machine_name(db, source_id: int) -> dict[str, SourceEntitlementRow]:
    rows = await repo.list_entitlements(db, source_id)
    return {row.machine_name: row for row in rows}


async def _set_status(db, entitlement_id: int, status: str) -> None:
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, entitlement_id)
        row.review_status = status


async def _set_md5(db, entitlement_id: int, md5: str | None) -> None:
    """The store re-uploading a file (a new digest) or serving a payload that
    omits the digest — both of which the sync copies straight onto the row."""
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, entitlement_id)
        row.md5 = md5


async def _later_arrival(
    db, source_id: int, machine_name: str, *, md5: str = SHARED_MD5
) -> int:
    """One more bundle selling the same file, arriving after the set is linked."""
    from foragerr.db.base import utcnow

    async with db.write_session() as session:
        now = utcnow()
        row = SourceEntitlementRow(
            source_id=source_id,
            gamekey=f"gamekey-{machine_name}",
            machine_name=machine_name,
            human_name="Example Saga Vol. 1",
            bundle_human_name="Example Later Bundle",
            classification="comic",
            review_status="new",
            md5=md5,
            filename="CBZ",
            formats_json="[]",
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        return row.id


# --- linking at sync ---------------------------------------------------------


@pytest.mark.req("FRG-SRC-015")
async def test_two_bundles_one_file_reviews_as_one_row(db, config_dir):
    source, result = await _twin_source(db, config_dir)

    rows = await _by_machine_name(db, source.id)
    canonical = rows["first_saga_v1"]
    copy = rows["second_saga_v1"]

    assert canonical.review_status == "new"
    assert canonical.duplicate_of is None
    # The later arrival parks behind the EARLIER row (lowest id), not the other
    # way round: the canonical is the one the operator has already been looking at.
    assert copy.review_status == "duplicate"
    assert copy.duplicate_of == canonical.id
    assert result.duplicates_parked == 1

    pending = await repo.list_entitlements(db, source.id, review_status="new")
    assert copy.id not in {row.id for row in pending}
    # The unrelated purchase is untouched — linking is md5 equality, nothing else.
    assert rows["first_other"].review_status == "new"


@pytest.mark.req("FRG-SRC-015")
async def test_an_entitlement_without_an_md5_never_links(db, config_dir):
    source, result = await _twin_source(db, config_dir, second_md5=None)

    rows = await _by_machine_name(db, source.id)
    assert rows["second_saga_v1"].md5 is None
    assert rows["second_saga_v1"].review_status == "new"
    assert result.duplicates_parked == 0


@pytest.mark.req("FRG-SRC-015")
async def test_distinct_md5s_never_link(db, config_dir):
    source, _result = await _twin_source(db, config_dir, second_md5=THIRD_MD5)

    rows = await _by_machine_name(db, source.id)
    # Same title, same series, different bytes — two real copies to review.
    assert rows["second_saga_v1"].review_status == "new"
    assert rows["second_saga_v1"].duplicate_of is None


@pytest.mark.req("FRG-SRC-015")
async def test_a_resync_never_re_parks_or_re_points_a_decided_row(db, config_dir):
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)
    copy_id = rows["second_saga_v1"].id
    await review.restore_entitlement(db, copy_id)
    await _set_status(db, rows["first_saga_v1"].id, "matched")

    # A later sync finds the set no longer all-``new`` (its twin is decided), so
    # the restored copy stays independently reviewable.
    parked = await link_duplicate_entitlements(db, source.id)

    refreshed = await repo.get_entitlement(db, copy_id)
    assert parked == 0
    assert refreshed.review_status == "new"
    assert refreshed.duplicate_of is None


# --- the one-time upgrade backfill -------------------------------------------


@pytest.mark.req("FRG-SRC-015")
async def test_backfill_links_existing_all_new_sets_and_is_idempotent(
    db, config_dir, monkeypatch
):
    """The upgrade shape: rows that synced before linking existed."""
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)
    copy_id = rows["second_saga_v1"].id
    # Unlink, reproducing the pre-0032 state of an install being upgraded.
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, copy_id)
        row.review_status = "new"
        row.duplicate_of = None

    app = type("App", (), {"state": type("State", (), {"db": db})()})()
    await duplicate_backfill_startup_hook(app)
    linked = await repo.get_entitlement(db, copy_id)
    assert linked.review_status == "duplicate"
    assert linked.duplicate_of == rows["first_saga_v1"].id

    # Idempotent by construction: the set is no longer all-``new``.
    await duplicate_backfill_startup_hook(app)
    again = await repo.get_entitlement(db, copy_id)
    assert again.duplicate_of == rows["first_saga_v1"].id
    assert (
        len(await repo.list_entitlements(db, source.id, review_status="duplicate")) == 1
    )


@pytest.mark.req("FRG-SRC-015")
async def test_backfill_leaves_a_set_with_a_decided_member_untouched(db, config_dir):
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)
    copy_id = rows["second_saga_v1"].id
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, copy_id)
        row.review_status = "new"
        row.duplicate_of = None
    # The operator had already ignored the earlier row before the upgrade.
    await _set_status(db, rows["first_saga_v1"].id, "ignored")

    app = type("App", (), {"state": type("State", (), {"db": db})()})()
    await duplicate_backfill_startup_hook(app)

    untouched = await repo.get_entitlement(db, copy_id)
    assert untouched.review_status == "new"
    assert untouched.duplicate_of is None


@pytest.mark.req("FRG-SRC-015")
async def test_a_failing_backfill_never_blocks_boot(db, config_dir, monkeypatch):
    def _explode(*_args, **_kwargs):
        raise RuntimeError("synthetic linking failure")

    monkeypatch.setattr(
        "foragerr.sources.dedupe.link_duplicate_entitlements", _explode
    )
    app = type("App", (), {"state": type("State", (), {"db": db})()})()
    await duplicate_backfill_startup_hook(app)  # logged, not raised


# --- a parked copy never downloads -------------------------------------------


@pytest.mark.req("FRG-SRC-015")
async def test_accept_refuses_a_parked_copy(db, config_dir):
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)
    copy_id = rows["second_saga_v1"].id
    commands = FakeCommands()

    with pytest.raises(review.EntitlementActionError) as accept_refusal:
        await review.accept_entitlement(
            db, None, copy_id, commands=commands, matched_via=MATCHED_VIA_OPERATOR
        )
    assert accept_refusal.value.status == 409

    still_parked = await repo.get_entitlement(db, copy_id)
    assert still_parked.review_status == "duplicate"
    assert still_parked.download_state is None
    assert commands.grabs() == []


@pytest.mark.req("FRG-SRC-015")
async def test_bulk_accept_skips_a_parked_copy_and_still_runs_the_rest(
    db, config_dir, root_folder_id, format_profile_id
):
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=902, title="Example Other Title"
    )
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, rows["first_other"].id)
        row.proposed_series_id = series_id
        row.proposed_match_json = json.dumps(
            {"kind": "library", "series_id": series_id, "title": "Example Other Title"}
        )
    commands = FakeCommands()

    result = await review.bulk_accept(
        db,
        None,
        [rows["second_saga_v1"].id, rows["first_other"].id],
        commands=commands,
        matched_via=MATCHED_VIA_OPERATOR,
    )

    assert result.applied == 1
    assert list(result.errors) == [rows["second_saga_v1"].id]
    assert (await repo.get_entitlement(db, rows["second_saga_v1"].id)).review_status == (
        "duplicate"
    )


@pytest.mark.req("FRG-SRC-015")
async def test_auto_sync_never_proposes_or_accepts_a_parked_copy(db, config_dir):
    """Auto-sync acts on the enrichment pass's pending set, which is ``new``-only
    — so a parked copy is never even a candidate for automatic acceptance."""
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)

    pending_ids = {
        row.id for row in await repo.list_entitlements(db, source.id, review_status="new")
    }
    assert rows["second_saga_v1"].id not in pending_ids


@pytest.mark.req("FRG-SRC-015")
async def test_apply_to_group_skips_a_parked_copy(
    db, config_dir, root_folder_id, format_profile_id
):
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=903, title="Example Saga"
    )

    result = await review.bulk_apply_to_group(
        db,
        None,
        [rows["first_saga_v1"].id, rows["second_saga_v1"].id],
        series_id=series_id,
        matched_via=MATCHED_VIA_OPERATOR,
    )

    assert result.applied == 1
    assert list(result.errors) == [rows["second_saga_v1"].id]


# --- recovery ----------------------------------------------------------------


@pytest.mark.req("FRG-SRC-004")
async def test_restore_returns_a_copy_to_independent_review(db, config_dir):
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)
    copy_id = rows["second_saga_v1"].id

    restored = await review.restore_entitlement(db, copy_id)

    assert restored.review_status == "new"
    assert restored.duplicate_of is None
    # The proposal is recomputed, exactly as a restore from ``ignored`` does.
    assert restored.proposed_match_json is None or restored.proposed_series_id is None


@pytest.mark.req("FRG-SRC-004")
async def test_restore_still_refuses_a_matched_row_with_the_ignored_wording(
    db, config_dir, root_folder_id, format_profile_id
):
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)
    await _set_status(db, rows["first_other"].id, "matched")

    with pytest.raises(review.EntitlementActionError) as refusal:
        await review.restore_entitlement(db, rows["first_other"].id)

    assert refusal.value.status == 409
    assert "not ignored" in str(refusal.value)


@pytest.mark.req("FRG-SRC-015")
async def test_ignoring_a_parked_copy_takes_it_out_of_the_set(db, config_dir):
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)
    copy_id = rows["second_saga_v1"].id

    ignored = await review.ignore_entitlement(db, copy_id)

    assert ignored.review_status == "ignored"
    assert ignored.duplicate_of is None
    # The canonical no longer claims it as a copy.
    assert await repo.duplicate_copies(db, [rows["first_saga_v1"].id]) == {}


@pytest.mark.req("FRG-SRC-015")
async def test_a_canonical_discloses_its_copies_and_their_bundles(db, config_dir):
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)

    copies = await repo.duplicate_copies(db, [row.id for row in rows.values()])

    assert copies == {rows["first_saga_v1"].id: ["Example Second Bundle"]}


@pytest.mark.req("FRG-SRC-015")
async def test_linking_is_bounded_to_one_source(db, config_dir):
    """Two stores selling the same bytes are two purchases with two
    provenances; cross-source dedupe is an explicit non-goal."""
    source_a, _result = await _twin_source(db, config_dir)
    source_b = await repo.create_source(
        db,
        source_type=TYPE_HUMBLE,
        name="Second Example Store",
        settings=HumbleSettings(session_cookie="SYNTH-COOKIE-2"),
    )
    async with db.write_session() as session:
        rows = (
            (
                await session.execute(
                    select(SourceEntitlementRow).where(
                        SourceEntitlementRow.source_id == source_a.id,
                        SourceEntitlementRow.md5 == SHARED_MD5,
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.review_status = "new"
            row.duplicate_of = None
        session.add(
            SourceEntitlementRow(
                source_id=source_b.id,
                gamekey="other-store-key",
                machine_name="other_store_saga",
                human_name="Example Saga Vol. 1",
                classification="comic",
                review_status="new",
                md5=SHARED_MD5,
                filename="CBZ",
                formats_json="[]",
                created_at=rows[0].created_at,
                updated_at=rows[0].updated_at,
            )
        )

    await link_duplicate_entitlements(db)

    other = [
        row
        for row in await repo.list_entitlements(db, source_b.id)
        if row.machine_name == "other_store_saga"
    ][0]
    assert other.review_status == "new"
    assert other.duplicate_of is None


# --- a set that keeps growing -------------------------------------------------


@pytest.mark.req("FRG-SRC-015")
async def test_a_third_and_fourth_bundle_park_onto_the_same_canonical(db, config_dir):
    """A store keeps re-selling one file. Every later arrival collapses onto the
    row the operator is already looking at — and points AT it, never at the copy
    parked before it, so one chip discloses the whole set."""
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)
    canonical_id = rows["first_saga_v1"].id
    third = await _later_arrival(db, source.id, "third_saga_v1")

    assert await link_duplicate_entitlements(db, source.id) == 1

    third_row = await repo.get_entitlement(db, third)
    assert third_row.review_status == "duplicate"
    assert third_row.duplicate_of == canonical_id

    fourth = await _later_arrival(db, source.id, "fourth_saga_v1")
    assert await link_duplicate_entitlements(db, source.id) == 1
    assert (await repo.get_entitlement(db, fourth)).duplicate_of == canonical_id
    copies = await repo.duplicate_copies(db, [canonical_id])
    assert len(copies[canonical_id]) == 3


@pytest.mark.req("FRG-SRC-015")
async def test_a_decided_member_freezes_the_set_against_later_arrivals(db, config_dir):
    """The operator has matched one member: the set is theirs now, so a later
    arrival stays independently reviewable rather than being hidden behind a
    decision that was never made about it."""
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)
    await _set_status(db, rows["first_saga_v1"].id, "matched")
    third = await _later_arrival(db, source.id, "third_saga_v1")

    assert await link_duplicate_entitlements(db, source.id) == 0

    assert (await repo.get_entitlement(db, third)).review_status == "new"


@pytest.mark.req("FRG-SRC-015")
async def test_replaying_the_linking_pass_parks_nothing_further(db, config_dir):
    source, result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)

    assert result.duplicates_parked == 1
    assert await link_duplicate_entitlements(db, source.id) == 0
    assert await link_duplicate_entitlements(db, source.id) == 0

    replayed = await _by_machine_name(db, source.id)
    assert replayed["second_saga_v1"].duplicate_of == rows["first_saga_v1"].id
    assert replayed["first_saga_v1"].review_status == "new"


# --- the bytes stop matching --------------------------------------------------


@pytest.mark.req("FRG-SRC-015")
async def test_a_copy_whose_md5_changes_returns_to_review(db, config_dir):
    """The store re-uploaded this copy's file. It is no longer the same bytes as
    the canonical, so keeping it parked would hide a file the operator owns and
    has never seen."""
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)
    copy_id = rows["second_saga_v1"].id
    await _set_md5(db, copy_id, THIRD_MD5)

    await link_duplicate_entitlements(db, source.id)

    unparked = await repo.get_entitlement(db, copy_id)
    assert unparked.review_status == "new"
    assert unparked.duplicate_of is None


@pytest.mark.req("FRG-SRC-015")
async def test_a_canonical_whose_md5_changes_frees_its_copies(db, config_dir):
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)
    copy_id = rows["second_saga_v1"].id
    await _set_md5(db, rows["first_saga_v1"].id, THIRD_MD5)

    await link_duplicate_entitlements(db, source.id)

    unparked = await repo.get_entitlement(db, copy_id)
    assert unparked.review_status == "new"
    assert unparked.duplicate_of is None


@pytest.mark.req("FRG-SRC-015")
async def test_a_copy_whose_md5_is_gone_returns_to_review(db, config_dir):
    """A row with no digest is never LINKED, so it must not stay linked either —
    absence of the signal is not evidence of identity in either direction."""
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)
    copy_id = rows["second_saga_v1"].id
    await _set_md5(db, copy_id, None)

    await link_duplicate_entitlements(db, source.id)

    unparked = await repo.get_entitlement(db, copy_id)
    assert unparked.review_status == "new"
    assert unparked.duplicate_of is None


# --- restore is a decision, not a nudge ---------------------------------------


@pytest.mark.req("FRG-SRC-015")
async def test_a_restored_copy_survives_the_next_linking_pass(db, config_dir):
    """Without the opt-out the very next sync re-parked the row, so the operator
    had to restore it again after every sync — an operator action silently
    reversed by a background pass."""
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)
    copy_id = rows["second_saga_v1"].id
    await review.restore_entitlement(db, copy_id)

    assert await link_duplicate_entitlements(db, source.id) == 0

    still_free = await repo.get_entitlement(db, copy_id)
    assert still_free.review_status == "new"
    assert still_free.duplicate_of is None
    assert still_free.dedupe_opt_out is True


@pytest.mark.req("FRG-SRC-015")
async def test_an_opted_out_row_can_still_be_a_canonical(db, config_dir):
    """The flag says "never park THIS row", not "never let it represent a set" —
    it is an ordinary reviewable row, and a later arrival collapses onto it."""
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)
    copy_id = rows["second_saga_v1"].id
    await review.restore_entitlement(db, copy_id)
    # The original canonical's file was re-uploaded, so it leaves the set.
    await _set_md5(db, rows["first_saga_v1"].id, THIRD_MD5)
    later = await _later_arrival(db, source.id, "third_saga_v1")

    assert await link_duplicate_entitlements(db, source.id) == 1

    assert (await repo.get_entitlement(db, copy_id)).review_status == "new"
    assert (await repo.get_entitlement(db, later)).duplicate_of == copy_id


@pytest.mark.req("FRG-SRC-015")
async def test_the_opt_out_survives_an_ignore_and_restore_cycle(db, config_dir):
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)
    copy_id = rows["second_saga_v1"].id

    await review.restore_entitlement(db, copy_id)
    await review.ignore_entitlement(db, copy_id)
    restored = await review.restore_entitlement(db, copy_id)

    assert restored.dedupe_opt_out is True
    assert await link_duplicate_entitlements(db, source.id) == 0
    assert (await repo.get_entitlement(db, copy_id)).review_status == "new"


@pytest.mark.req("FRG-SRC-004")
async def test_restoring_an_ignored_row_never_invents_an_opt_out(db, config_dir):
    """The flag records a decision about DUPLICATE parking; an ordinary ignore /
    restore round trip has made no such decision."""
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)
    plain_id = rows["first_other"].id
    await review.ignore_entitlement(db, plain_id)

    restored = await review.restore_entitlement(db, plain_id)

    assert restored.dedupe_opt_out is False


# --- the direct row actions refuse a copy -------------------------------------


@pytest.mark.req("FRG-SRC-015")
async def test_a_direct_match_refuses_a_parked_copy(
    db, config_dir, root_folder_id, format_profile_id
):
    """The operator's own match carries no ``new`` precondition — re-deciding a
    matched row is legitimate — but a parked copy is not a decision to revisit:
    resolving it queues the bytes the canonical already represents."""
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)
    copy_id = rows["second_saga_v1"].id
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=911, title="Example Saga"
    )
    commands = FakeCommands()

    with pytest.raises(review.EntitlementActionError) as refusal:
        await review.match_entitlement(
            db,
            copy_id,
            series_id=series_id,
            commands=commands,
            matched_via=MATCHED_VIA_OPERATOR,
        )

    assert refusal.value.status == 409
    still_parked = await repo.get_entitlement(db, copy_id)
    assert still_parked.review_status == "duplicate"
    assert still_parked.duplicate_of == rows["first_saga_v1"].id
    assert still_parked.matched_series_id is None
    assert commands.grabs() == []


@pytest.mark.req("FRG-SRC-015")
async def test_a_direct_add_refuses_a_parked_copy(db, config_dir):
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)
    copy_id = rows["second_saga_v1"].id
    commands = FakeCommands()

    with pytest.raises(review.EntitlementActionError) as refusal:
        await review.add_entitlement(
            db,
            None,
            copy_id,
            commands=commands,
            cv_volume_id=912,
            matched_via=MATCHED_VIA_OPERATOR,
        )

    assert refusal.value.status == 409
    still_parked = await repo.get_entitlement(db, copy_id)
    assert still_parked.review_status == "duplicate"
    assert still_parked.duplicate_of == rows["first_saga_v1"].id
    assert commands.grabs() == []


@pytest.mark.req("FRG-SRC-015")
async def test_bulk_match_reports_a_parked_copy_and_still_matches_the_rest(
    db, config_dir, root_folder_id, format_profile_id
):
    source, _result = await _twin_source(db, config_dir)
    rows = await _by_machine_name(db, source.id)
    copy_id = rows["second_saga_v1"].id
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=913, title="Example Saga"
    )

    result = await review.bulk_match(
        db,
        [rows["first_other"].id, copy_id],
        series_id=series_id,
        commands=FakeCommands(),
        matched_via=MATCHED_VIA_OPERATOR,
    )

    assert result.applied == 1
    assert list(result.errors) == [copy_id]
    assert "restore it first" in result.errors[copy_id]
    assert (await repo.get_entitlement(db, copy_id)).review_status == "duplicate"
