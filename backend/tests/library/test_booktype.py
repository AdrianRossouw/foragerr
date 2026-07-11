"""Series collected-edition (trade) book-type typing (FRG-SER-018).

`detect_series_booktype` is the pure title -> book-type derivation reusing the
filename parser's own book-type cue vocabulary (never a second cue list). The
type is auto-derived at add and at refresh unless the operator locked it via
the edit override; a locked type survives refresh, and clearing the lock
re-derives on the next refresh (mirroring the grouping-override precedent).
Typing is display/naming metadata only — it never touches wanted state
(that invariant is FRG-SER-019, tested in test_trade_non_suppression.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from foragerr.commands import CommandService
from foragerr.library import repo
from foragerr.library.booktype import COLLECTED_BOOKTYPES, detect_series_booktype
from foragerr.library.flows import (
    BooktypeEdit,
    SeriesValidationError,
    add_series,
    edit_series,
    refresh_series,
)

from flows_support import FakeCV, build_factory, flows_settings, issue


# --- unit: detect_series_booktype -------------------------------------------


@pytest.mark.req("FRG-SER-018")
@pytest.mark.parametrize(
    "title, expected",
    [
        ("Batman: The Long Halloween (TPB)", "tpb"),
        ("Y The Last Man Trade Paperback", "tpb"),
        ("Saga Digital TPB", "tpb"),
        ("Watchmen (Graphic Novel)", "gn"),
        ("Some Collection GN", "gn"),
        ("The Sandman Hardcover", "hc"),
        ("Absolute Batman HC", "hc"),
    ],
)
def test_cue_titles_are_typed(title, expected):
    assert detect_series_booktype(title) == expected


@pytest.mark.req("FRG-SER-018")
@pytest.mark.parametrize(
    "title",
    [
        "Batman (2011)",
        "Saga",
        "Saga Deluxe Edition",  # an EDITION_TAG, not a book-type cue
        "Paper Girls",
    ],
)
def test_no_cue_title_is_null(title):
    assert detect_series_booktype(title) is None


@pytest.mark.req("FRG-SER-018")
@pytest.mark.parametrize(
    "title",
    [
        "Gunslinger Spawn",  # "gn" only as a whole word, never inside "Gunslinger"
        "Archie",            # "hc" never inside "Archie"
        "The Punisher",      # "hc" never inside "Punisher"... nor "Thc"
        "Watchmen",          # "hc" never inside "Watchmen"
    ],
)
def test_cue_inside_a_word_never_fires(title):
    assert detect_series_booktype(title) is None


@pytest.mark.req("FRG-SER-018")
def test_detected_values_are_within_the_allowed_vocabulary():
    for title in ("A TPB", "A GN", "A HC"):
        assert detect_series_booktype(title) in COLLECTED_BOOKTYPES


# --- auto-derive at add + refresh, and the operator override ----------------


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return flows_settings(cfg)


@pytest.fixture
async def commands(db, settings, command_registry):
    return CommandService(db, settings)


async def _add(db, settings, commands, root_folder_id, *, cv_volume_id, name):
    factory = build_factory(settings, FakeCV().volume(cv_volume_id, name=name).handler())
    result = await add_series(
        db,
        settings,
        cv_volume_id=cv_volume_id,
        root_folder_id=root_folder_id,
        commands=commands,
        enqueue_refresh=False,
        factory=factory,
    )
    return result.series.id


async def _refresh(db, settings, commands, sid, name):
    async with db.read_session() as session:
        cv_id = (await repo.get_series(session, sid)).cv_volume_id
    factory = build_factory(
        settings,
        FakeCV().volume(cv_id, name=name).issues(cv_id, [issue(cv_id * 10, "1")]).handler(),
    )
    await refresh_series(db, settings, sid, commands=commands, factory=factory)


@pytest.mark.req("FRG-SER-018")
async def test_cue_title_is_auto_typed_at_add_and_no_cue_is_null(
    db, settings, commands, root_folder_id, format_profile_id
):
    trade = await _add(
        db, settings, commands, root_folder_id, cv_volume_id=1,
        name="Batman: The Long Halloween (TPB)",
    )
    single = await _add(
        db, settings, commands, root_folder_id, cv_volume_id=2, name="Batman (2011)"
    )
    async with db.read_session() as session:
        assert (await repo.get_series(session, trade)).booktype == "tpb"
        st = await repo.get_series(session, single)
        assert st.booktype is None
        assert st.booktype_locked is False


@pytest.mark.req("FRG-SER-018")
async def test_auto_type_re_derives_at_refresh_when_unlocked(
    db, settings, commands, root_folder_id, format_profile_id
):
    sid = await _add(
        db, settings, commands, root_folder_id, cv_volume_id=3, name="Saga Hardcover"
    )
    async with db.read_session() as session:
        assert (await repo.get_series(session, sid)).booktype == "hc"
    # Refresh keeps the same title -> stable type (never touches title).
    await _refresh(db, settings, commands, sid, "Saga Hardcover")
    async with db.read_session() as session:
        assert (await repo.get_series(session, sid)).booktype == "hc"


@pytest.mark.req("FRG-SER-018")
async def test_operator_override_sets_locks_and_survives_refresh(
    db, settings, commands, root_folder_id, format_profile_id
):
    # A no-cue title -> auto-null, then the operator types it explicitly.
    sid = await _add(
        db, settings, commands, root_folder_id, cv_volume_id=4, name="Saga Collection"
    )
    async with db.read_session() as session:
        assert (await repo.get_series(session, sid)).booktype is None

    await edit_series(db, sid, booktype_op=BooktypeEdit(action="set", booktype="gn"))
    async with db.read_session() as session:
        s = await repo.get_series(session, sid)
        assert s.booktype == "gn"
        assert s.booktype_locked is True

    # Refresh must NOT re-derive over the locked operator choice.
    await _refresh(db, settings, commands, sid, "Saga Collection")
    async with db.read_session() as session:
        s = await repo.get_series(session, sid)
        assert s.booktype == "gn"
        assert s.booktype_locked is True


@pytest.mark.req("FRG-SER-018")
async def test_clearing_the_lock_re_derives_on_next_refresh(
    db, settings, commands, root_folder_id, format_profile_id
):
    # A cue title, overridden to a different explicit type (locked)...
    sid = await _add(
        db, settings, commands, root_folder_id, cv_volume_id=5, name="Kingdom TPB"
    )
    await edit_series(db, sid, booktype_op=BooktypeEdit(action="set", booktype="hc"))
    async with db.read_session() as session:
        s = await repo.get_series(session, sid)
        assert s.booktype == "hc" and s.booktype_locked is True

    # ...then clear the lock: the value is unchanged inline (re-derive is deferred).
    await edit_series(db, sid, booktype_op=BooktypeEdit(action="unlock"))
    async with db.read_session() as session:
        s = await repo.get_series(session, sid)
        assert s.booktype == "hc"  # unlock alone doesn't re-derive
        assert s.booktype_locked is False

    # Next refresh re-derives from the title cue -> back to tpb.
    await _refresh(db, settings, commands, sid, "Kingdom TPB")
    async with db.read_session() as session:
        assert (await repo.get_series(session, sid)).booktype == "tpb"


# --- add-time explicit book-type override (FRG-SER-005/018) -----------------


async def _add_override(
    db, settings, commands, root_folder_id, *, cv_volume_id, name, booktype,
    booktype_locked,
):
    """Add a series passing the optional add-time book-type override."""
    factory = build_factory(settings, FakeCV().volume(cv_volume_id, name=name).handler())
    result = await add_series(
        db,
        settings,
        cv_volume_id=cv_volume_id,
        root_folder_id=root_folder_id,
        commands=commands,
        enqueue_refresh=False,
        booktype=booktype,
        booktype_locked=booktype_locked,
        factory=factory,
    )
    return result.series.id


@pytest.mark.req("FRG-SER-018")
@pytest.mark.req("FRG-SER-005")
async def test_add_time_explicit_booktype_locks_and_skips_derivation(
    db, settings, commands, root_folder_id, format_profile_id
):
    # Title cue would derive "gn"; the explicit "tpb" override wins and locks,
    # so derivation is skipped at add and never re-derived at refresh.
    assert detect_series_booktype("Nimona Graphic Novel") == "gn"
    sid = await _add_override(
        db, settings, commands, root_folder_id, cv_volume_id=31,
        name="Nimona Graphic Novel", booktype="tpb", booktype_locked=True,
    )
    async with db.read_session() as session:
        s = await repo.get_series(session, sid)
        assert s.booktype == "tpb"
        assert s.booktype_locked is True

    # Refresh over the same title must NOT re-derive over the locked choice.
    await _refresh(db, settings, commands, sid, "Nimona Graphic Novel")
    async with db.read_session() as session:
        s = await repo.get_series(session, sid)
        assert s.booktype == "tpb"
        assert s.booktype_locked is True


@pytest.mark.req("FRG-SER-018")
@pytest.mark.req("FRG-SER-005")
async def test_add_time_explicit_single_issues_locks_null(
    db, settings, commands, root_folder_id, format_profile_id
):
    # Title carries a TPB cue (derivation would say "tpb"), but the operator
    # explicitly chose single issues -> persisted NULL and locked.
    assert detect_series_booktype("Saga TPB") == "tpb"
    sid = await _add_override(
        db, settings, commands, root_folder_id, cv_volume_id=32,
        name="Saga TPB", booktype=None, booktype_locked=True,
    )
    async with db.read_session() as session:
        s = await repo.get_series(session, sid)
        assert s.booktype is None
        assert s.booktype_locked is True

    # A later refresh keeps the locked single-issues choice (no re-derive).
    await _refresh(db, settings, commands, sid, "Saga TPB")
    async with db.read_session() as session:
        s = await repo.get_series(session, sid)
        assert s.booktype is None
        assert s.booktype_locked is True


@pytest.mark.req("FRG-SER-018")
@pytest.mark.req("FRG-SER-005")
async def test_add_without_override_derives_exactly_as_before(
    db, settings, commands, root_folder_id, format_profile_id
):
    # Regression pin: absent the override (booktype_locked defaults False), the
    # add-time behavior is byte-identical to today — derive from the cue, unlocked.
    trade = await _add_override(
        db, settings, commands, root_folder_id, cv_volume_id=33,
        name="Saga TPB", booktype=None, booktype_locked=False,
    )
    single = await _add_override(
        db, settings, commands, root_folder_id, cv_volume_id=34,
        name="Batman (2011)", booktype=None, booktype_locked=False,
    )
    async with db.read_session() as session:
        t = await repo.get_series(session, trade)
        assert t.booktype == "tpb"
        assert t.booktype_locked is False
        s = await repo.get_series(session, single)
        assert s.booktype is None
        assert s.booktype_locked is False


@pytest.mark.req("FRG-SER-018")
async def test_set_with_a_bad_booktype_is_rejected(
    db, settings, commands, root_folder_id, format_profile_id
):
    sid = await _add(
        db, settings, commands, root_folder_id, cv_volume_id=6, name="Nailbiter"
    )
    with pytest.raises(SeriesValidationError):
        await edit_series(
            db, sid, booktype_op=BooktypeEdit(action="set", booktype="omnibus")
        )
    # The rejected edit left nothing behind.
    async with db.read_session() as session:
        s = await repo.get_series(session, sid)
        assert s.booktype is None and s.booktype_locked is False
