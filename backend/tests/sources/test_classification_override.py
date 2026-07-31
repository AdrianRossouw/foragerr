"""The operator's own classification of a review row (FRG-SRC-016).

The automatic classifier re-derives every ``new`` row's classification on every
sync from file shape + the library-wide publisher rules (FRG-SRC-012), so an
operator correction that carried no provenance would survive exactly until the
next sync. These tests pin the carve-out: an operator-marked row is skipped by
the write-back in BOTH directions, whatever the rules later say, and the mark
itself is refused on rows that are no longer in review.
"""

from __future__ import annotations

import pytest

from foragerr.sources import repo, review
from foragerr.sources.classify import PublisherRuleSet
from foragerr.sources.models import (
    CLASSIFIED_VIA_OPERATOR,
    MATCHED_VIA_OPERATOR,
    SourceEntitlementRow,
)
from foragerr.sources.registry import TYPE_HUMBLE
from foragerr.sources.review import EntitlementActionError, _is_grabbable
from foragerr.sources.service import run_sync
from foragerr.sources.settings import HumbleSettings
from sources_support import (  # noqa: F401 — imported fixtures
    GAMEKEY,
    _mk_series,
    fixture_bytes,
    format_profile_id,
    make_factory,
    order_handler,
    root_folder_id,
)

import httpx

#: The publisher the fixture's comics carry — named in a rule when a test needs
#: the AUTOMATIC classifier to disagree with the operator.
COMIC_PUBLISHER = "Synthetic Comics"

#: A fixture row the file-shape classifier calls a comic, carrying a publisher,
#: so a rule can be aimed at it.
COMIC_ROW = "synth_singleissue_01"

#: A fixture row the file-shape classifier calls non-comic (prose formats only).
NON_COMIC_ROW = "synth_prose_novel_epub_only"

#: A fixture row the file-shape classifier calls non-comic (a PDF shipped with a
#: prose twin) that DOES carry a grabbable format — the shape an operator marks
#: comic and then expects to be able to accept.
NON_COMIC_ROW_WITH_A_GRABBABLE_COPY = "synth_prose_with_pdf_twin"


async def _source(db, *, name: str = "Humble Bundle"):
    return await repo.create_source(
        db,
        source_type=TYPE_HUMBLE,
        name=name,
        settings=HumbleSettings(session_cookie="SYNTH-COOKIE"),
        connection_state="connected",
    )


async def _sync(db, config_dir, source, *, rules: str = ""):
    factory = make_factory(
        config_dir,
        httpx.MockTransport(
            order_handler(
                list_body=b'[{"gamekey":"%s"}]' % GAMEKEY.encode(),
                order_bodies={GAMEKEY: fixture_bytes("order_comics.json")},
            )
        ),
    )
    return await run_sync(
        db,
        factory,
        source,
        min_interval=0.0,
        publisher_rules=PublisherRuleSet.from_csv(rules),
    )


async def _row(db, source_id: int, machine_name: str) -> SourceEntitlementRow:
    rows = await repo.list_entitlements(db, source_id)
    return next(r for r in rows if r.machine_name == machine_name)


async def _park_as_duplicate(db, entitlement_id: int, canonical_id: int) -> None:
    """Stand in for the sync-time md5 linking pass (FRG-SRC-015) — the parking
    itself is covered in test_dedupe; here it is only a review state the mark
    has to refuse."""
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, entitlement_id)
        row.review_status = "duplicate"
        row.duplicate_of = canonical_id


# --- stickiness ---------------------------------------------------------------


@pytest.mark.req("FRG-SRC-016")
async def test_a_mark_survives_the_next_sync(db, config_dir):
    """The dogfood case: a row the file-shape classifier calls a comic, marked
    non-comic by hand, must not be re-derived back by the next sync."""
    source = await _source(db)
    await _sync(db, config_dir, source)
    row = await _row(db, source.id, COMIC_ROW)
    assert row.classification == "comic"

    marked = await review.classify_entitlement(db, row.id, classification="other")
    assert (marked.classification, marked.classified_via) == (
        "other",
        CLASSIFIED_VIA_OPERATOR,
    )

    await _sync(db, config_dir, source)

    after = await _row(db, source.id, COMIC_ROW)
    assert (after.classification, after.classified_via) == (
        "other",
        CLASSIFIED_VIA_OPERATOR,
    )
    assert after.review_status == "new"


@pytest.mark.req("FRG-SRC-016")
async def test_the_reverse_mark_is_symmetric_and_sticks(db, config_dir):
    """Marking back to comic is another OPERATOR mark, not a return to
    automatic: the file-shape verdict that made the row non-comic is just as
    permanently overridden."""
    source = await _source(db)
    await _sync(db, config_dir, source)
    row = await _row(db, source.id, NON_COMIC_ROW)
    assert row.classification == "other"

    marked = await review.classify_entitlement(db, row.id, classification="comic")
    assert (marked.classification, marked.classified_via) == (
        "comic",
        CLASSIFIED_VIA_OPERATOR,
    )

    await _sync(db, config_dir, source)

    after = await _row(db, source.id, NON_COMIC_ROW)
    assert (after.classification, after.classified_via) == (
        "comic",
        CLASSIFIED_VIA_OPERATOR,
    )


@pytest.mark.req("FRG-SRC-012")
async def test_a_publisher_rule_never_moves_an_operator_marked_row(db, config_dir):
    """A rule the operator has already overruled on one row: the automatic path
    classifies it ``other``, the operator has said ``comic``, and every later
    sync leaves it where the operator put it."""
    source = await _source(db)
    await _sync(db, config_dir, source, rules=COMIC_PUBLISHER)
    row = await _row(db, source.id, COMIC_ROW)
    assert row.classification == "other"
    await review.classify_entitlement(db, row.id, classification="comic")

    await _sync(db, config_dir, source, rules=COMIC_PUBLISHER)

    assert (await _row(db, source.id, COMIC_ROW)).classification == "comic"
    # The unmarked siblings still move, so the rule itself demonstrably fired.
    assert (
        await _row(db, source.id, "synth_collected_edition_vol1")
    ).classification == "other"


@pytest.mark.req("FRG-SRC-012")
async def test_removing_a_rule_never_moves_an_operator_marked_row(db, config_dir):
    """The other direction: a rule ADDED and then REMOVED under a row the
    operator marked non-comic. Removing a rule un-filters the rows it covered —
    but the marked row was never the rule's to hand back."""
    source = await _source(db)
    await _sync(db, config_dir, source)
    row = await _row(db, source.id, COMIC_ROW)
    assert row.classification == "comic"
    await review.classify_entitlement(db, row.id, classification="other")

    await _sync(db, config_dir, source, rules=COMIC_PUBLISHER)
    await _sync(db, config_dir, source)

    assert (await _row(db, source.id, COMIC_ROW)).classification == "other"
    assert (
        await _row(db, source.id, "synth_collected_edition_vol1")
    ).classification == "comic"


@pytest.mark.req("FRG-SRC-016")
async def test_the_sync_counters_report_the_stored_classification(db, config_dir):
    """A run counter describes what the rows CARRY after the sync. A marked row
    is not re-derived, so counting its freshly-derived value would over-report
    the classifier's reach."""
    source = await _source(db)
    baseline = await _sync(db, config_dir, source)
    assert (baseline.comic, baseline.other) == (3, 3)
    row = await _row(db, source.id, COMIC_ROW)
    await review.classify_entitlement(db, row.id, classification="other")

    result = await _sync(db, config_dir, source)

    assert (result.comic, result.other) == (2, 4)


# --- the marked row is a usable row -------------------------------------------


@pytest.mark.req("FRG-SRC-016")
async def test_a_row_marked_comic_is_grabbable(db, config_dir):
    """A mark the accept path cannot act on is no mark at all. The row's
    download identity (format/md5/size/filename) is parsed from the payload
    whatever the file shape said, so marking it comic makes it acceptable —
    rather than a comic row the grab gate silently refuses forever."""
    source = await _source(db)
    await _sync(db, config_dir, source)
    row = await _row(db, source.id, NON_COMIC_ROW_WITH_A_GRABBABLE_COPY)
    assert row.classification == "other"
    assert row.md5 is not None

    marked = await review.classify_entitlement(db, row.id, classification="comic")

    assert _is_grabbable(marked)
    assert marked.preferred_format == "PDF"
    assert (marked.md5, marked.filename) == (row.md5, row.filename)


@pytest.mark.req("FRG-SRC-016")
async def test_a_sync_never_re_nulls_a_marked_rows_download_identity(db, config_dir):
    """The other half: the sync write-back refreshes the identity fields on
    every row, and deriving them from the FRESH file-shape verdict re-nulled the
    marked row on every run — so the mark held but the row was permanently
    un-grabbable."""
    source = await _source(db)
    await _sync(db, config_dir, source)
    row = await _row(db, source.id, NON_COMIC_ROW_WITH_A_GRABBABLE_COPY)
    marked = await review.classify_entitlement(db, row.id, classification="comic")

    await _sync(db, config_dir, source)

    after = await _row(db, source.id, NON_COMIC_ROW_WITH_A_GRABBABLE_COPY)
    assert _is_grabbable(after)
    assert (after.md5, after.filename, after.file_size) == (
        marked.md5,
        marked.filename,
        marked.file_size,
    )


# --- preconditions ------------------------------------------------------------


@pytest.mark.req("FRG-SRC-004")
async def test_a_matched_row_refuses_the_mark(
    db, config_dir, root_folder_id, format_profile_id
):
    source = await _source(db)
    await _sync(db, config_dir, source)
    row = await _row(db, source.id, COMIC_ROW)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=7301, title="Synthetic Hero"
    )
    await review.match_entitlement(
        db,
        row.id,
        series_id=series_id,
        commands=None,
        matched_via=MATCHED_VIA_OPERATOR,
    )

    with pytest.raises(EntitlementActionError) as excinfo:
        await review.classify_entitlement(db, row.id, classification="other")

    assert excinfo.value.status == 409
    assert "already matched" in str(excinfo.value)
    after = await _row(db, source.id, COMIC_ROW)
    assert (after.classification, after.classified_via) == ("comic", None)


@pytest.mark.req("FRG-SRC-004")
async def test_an_ignored_row_refuses_the_mark_with_restore_first(db, config_dir):
    source = await _source(db)
    await _sync(db, config_dir, source)
    row = await _row(db, source.id, COMIC_ROW)
    await review.ignore_entitlement(db, row.id)

    with pytest.raises(EntitlementActionError) as excinfo:
        await review.classify_entitlement(db, row.id, classification="other")

    assert excinfo.value.status == 409
    assert "restore it first" in str(excinfo.value)


@pytest.mark.req("FRG-SRC-004")
async def test_a_parked_copy_refuses_the_mark(db, config_dir):
    """A ``duplicate`` row is parked, not in review — the one refusal every
    write path gives it (FRG-SRC-015) covers this one too."""
    source = await _source(db)
    await _sync(db, config_dir, source)
    canonical = await _row(db, source.id, COMIC_ROW)
    copy = await _row(db, source.id, "synth_collected_edition_vol1")
    await _park_as_duplicate(db, copy.id, canonical.id)

    with pytest.raises(EntitlementActionError) as excinfo:
        await review.classify_entitlement(db, copy.id, classification="other")

    assert excinfo.value.status == 409
    assert "restore it first" in str(excinfo.value)


@pytest.mark.req("FRG-SRC-016")
async def test_an_unknown_classification_is_refused(db, config_dir):
    source = await _source(db)
    await _sync(db, config_dir, source)
    row = await _row(db, source.id, COMIC_ROW)

    with pytest.raises(EntitlementActionError) as excinfo:
        await review.classify_entitlement(db, row.id, classification="rpg")

    assert excinfo.value.status == 422
    assert (await _row(db, source.id, COMIC_ROW)).classified_via is None


@pytest.mark.req("FRG-SRC-016")
async def test_a_missing_row_is_a_404(db, config_dir):
    source = await _source(db)
    await _sync(db, config_dir, source)

    with pytest.raises(EntitlementActionError) as excinfo:
        await review.classify_entitlement(db, 999_999, classification="other")

    assert excinfo.value.status == 404


# --- bulk ---------------------------------------------------------------------


@pytest.mark.req("FRG-SRC-016")
async def test_bulk_mark_applies_the_reviewable_rows_and_reports_the_rest(
    db, config_dir, root_folder_id, format_profile_id
):
    """The bundle-selection case (a selection spans buckets the moment "select
    all" is used): every ``new`` row is marked, and each row that cannot be
    reports its own reason without costing the batch."""
    source = await _source(db)
    await _sync(db, config_dir, source)
    markable = await _row(db, source.id, COMIC_ROW)
    matched = await _row(db, source.id, "synth_collected_edition_vol1")
    ignored = await _row(db, source.id, "synth_artbook_pdf_only")
    parked = await _row(db, source.id, NON_COMIC_ROW)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=7302, title="Synthetic Hero"
    )
    await review.match_entitlement(
        db,
        matched.id,
        series_id=series_id,
        commands=None,
        matched_via=MATCHED_VIA_OPERATOR,
    )
    await review.ignore_entitlement(db, ignored.id)
    await _park_as_duplicate(db, parked.id, markable.id)

    result = await review.bulk_classify(
        db,
        [markable.id, matched.id, ignored.id, parked.id],
        classification="other",
    )

    assert (result.applied, result.skipped) == (1, 3)
    assert set(result.errors) == {matched.id, ignored.id, parked.id}
    assert (await _row(db, source.id, COMIC_ROW)).classification == "other"
    assert (
        await _row(db, source.id, "synth_collected_edition_vol1")
    ).classification == "comic"


@pytest.mark.req("FRG-SRC-016")
async def test_bulk_mark_comic_is_the_symmetric_action(db, config_dir):
    source = await _source(db)
    await _sync(db, config_dir, source)
    rows = [
        await _row(db, source.id, NON_COMIC_ROW),
        await _row(db, source.id, "synth_prose_with_pdf_twin"),
    ]

    result = await review.bulk_classify(
        db, [r.id for r in rows], classification="comic"
    )

    assert (result.applied, result.skipped) == (2, 0)
    for row in rows:
        after = await repo.get_entitlement(db, row.id)
        assert (after.classification, after.classified_via) == (
            "comic",
            CLASSIFIED_VIA_OPERATOR,
        )


# --- agreement is not a claim ---------------------------------------------------


@pytest.mark.req("FRG-SRC-012")
async def test_marking_a_row_to_what_it_already_says_leaves_the_rules_owning_it(
    db, config_dir
):
    """A bulk mark at bundle scale covers rows the classifier already called
    right. Stamping provenance on those would exempt them from every later
    publisher-rule edit, so FRG-SRC-012's "removing a default un-filters" would
    silently stop reaching them. The action reports applied and writes nothing.
    """
    source = await _source(db)
    await _sync(db, config_dir, source, rules=COMIC_PUBLISHER)
    row = await _row(db, source.id, COMIC_ROW)
    assert (row.classification, row.classified_via) == ("other", None)

    result = await review.bulk_classify(db, [row.id], classification="other")

    assert (result.applied, result.skipped) == (1, 0)
    assert (await _row(db, source.id, COMIC_ROW)).classified_via is None
    # Proof the row is still the rules': removing the rule hands it back.
    await _sync(db, config_dir, source)
    assert (await _row(db, source.id, COMIC_ROW)).classification == "comic"


@pytest.mark.req("FRG-SRC-016")
async def test_re_marking_an_operator_marked_row_to_the_same_value_is_a_no_op(
    db, config_dir
):
    source = await _source(db)
    await _sync(db, config_dir, source)
    row = await _row(db, source.id, COMIC_ROW)
    marked = await review.classify_entitlement(db, row.id, classification="other")

    again = await review.classify_entitlement(db, row.id, classification="other")

    assert (again.classification, again.classified_via) == (
        "other",
        CLASSIFIED_VIA_OPERATOR,
    )
    assert again.updated_at == marked.updated_at


# --- the mark travels with the row ----------------------------------------------


@pytest.mark.req("FRG-SRC-016")
async def test_a_parked_marked_row_keeps_its_provenance_through_restore(
    db, config_dir
):
    """Ignoring a marked row and restoring it must not hand it back to the
    classifier: restore is the way back INTO review, not a reset of what the
    operator said the row is."""
    source = await _source(db)
    await _sync(db, config_dir, source)
    row = await _row(db, source.id, COMIC_ROW)
    await review.classify_entitlement(db, row.id, classification="other")
    await review.ignore_entitlement(db, row.id)

    restored = await review.restore_entitlement(db, row.id)

    assert restored.review_status == "new"
    assert (restored.classification, restored.classified_via) == (
        "other",
        CLASSIFIED_VIA_OPERATOR,
    )
    # And it is still the operator's after the next sync re-derives its siblings.
    await _sync(db, config_dir, source)
    assert (await _row(db, source.id, COMIC_ROW)).classification == "other"


@pytest.mark.req("FRG-SRC-016")
async def test_restoring_a_non_comic_row_spends_no_comicvine_budget(db, config_dir):
    """ComicVine is 200 requests/hour per path. A non-comic row has nothing the
    catalog could propose, so restoring one — or a whole non-comic selection —
    must not buy a lookup no surface will ever show."""

    class _CountingCV:
        def __init__(self):
            self.calls = 0

        async def suggest_series(self, term):
            self.calls += 1
            raise AssertionError("a non-comic restore must not reach ComicVine")

    source = await _source(db)
    await _sync(db, config_dir, source)
    row = await _row(db, source.id, NON_COMIC_ROW)
    await review.ignore_entitlement(db, row.id)
    before = await repo.get_entitlement(db, row.id)

    cv = _CountingCV()
    restored = await review.restore_entitlement(
        db, row.id, cv_client=cv, cv_configured=True
    )

    assert cv.calls == 0
    assert restored.review_status == "new"
    assert restored.proposed_match_json == before.proposed_match_json
    assert restored.proposed_series_id == before.proposed_series_id
