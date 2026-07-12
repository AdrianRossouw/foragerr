"""One-time unseed data fix for v0.5.0-derived follows (FRG-CRTR-004).

The owner decision of 2026-07-11 forbids any derived follow. The v0.5.0 backbone
seeded ``followed`` for creators crossing a ≥2-distinct-series threshold; those
rows are ``followed = true`` with ``follow_touched IS NULL`` (an explicit follow
carries the touched marker). :func:`creators_unseed_startup_hook` clears exactly
those seeded rows once per database, spares explicit follows, is marker-gated
(one-shot), runs even on an empty library, and is ordered BEFORE the backfill
hook in ``create_app``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from foragerr.app import create_app
from foragerr.creators.commands import (
    UNSEED_MARKER_KEY,
    creators_backfill_startup_hook,
    creators_unseed_startup_hook,
    is_unseed_complete,
)
from foragerr.creators.models import CreatorRow
from foragerr.db.base import utcnow

from http_support import make_settings


def _app_double(db) -> SimpleNamespace:
    """Minimal app stand-in exposing ``state.db`` for the startup hook."""
    return SimpleNamespace(state=SimpleNamespace(db=db))


async def _add_creator(
    db, *, cv_person_id, name, followed, touched
) -> int:
    now = utcnow()
    async with db.write_session() as session:
        row = CreatorRow(
            cv_person_id=cv_person_id,
            name=name,
            followed=followed,
            follow_touched=now if touched else None,
            followed_at=now if followed else None,
            created_at=now,
        )
        session.add(row)
        await session.flush()
        return row.id


async def _get(db, creator_id: int) -> CreatorRow:
    async with db.read_session() as session:
        return await session.get(CreatorRow, creator_id)


# --- FRG-CRTR-004: the unseed data fix --------------------------------------


@pytest.mark.req("FRG-CRTR-004")
async def test_unseed_clears_seeded_and_spares_explicit(db):
    """Seeded rows (followed, follow_touched NULL) flip to unfollowed with a
    cleared ``followed_at``; explicit follows/unfollows (follow_touched set)
    survive untouched; the marker is laid down."""
    seeded = await _add_creator(
        db, cv_person_id=10, name="Seeded", followed=True, touched=False
    )
    explicit_follow = await _add_creator(
        db, cv_person_id=11, name="ExplicitFollow", followed=True, touched=True
    )
    explicit_unfollow = await _add_creator(
        db, cv_person_id=12, name="ExplicitUnfollow", followed=False, touched=True
    )
    plain = await _add_creator(
        db, cv_person_id=13, name="Plain", followed=False, touched=False
    )

    await creators_unseed_startup_hook(_app_double(db))

    seeded_row = await _get(db, seeded)
    assert seeded_row.followed is False  # derived follow cleared
    assert seeded_row.followed_at is None
    assert seeded_row.follow_touched is None

    follow_row = await _get(db, explicit_follow)
    assert follow_row.followed is True  # explicit follow spared
    assert follow_row.follow_touched is not None

    unfollow_row = await _get(db, explicit_unfollow)
    assert unfollow_row.followed is False  # explicit unfollow spared
    assert unfollow_row.follow_touched is not None

    plain_row = await _get(db, plain)
    assert plain_row.followed is False  # already unfollowed, untouched

    assert await is_unseed_complete(db)


@pytest.mark.req("FRG-CRTR-004")
async def test_unseed_is_one_shot(db):
    """Once the marker is set, a later seeded-looking row is NOT cleared: the fix
    runs at most once per database."""
    await creators_unseed_startup_hook(_app_double(db))
    assert await is_unseed_complete(db)

    # A row that looks seeded appears after the fix already ran (marker set).
    late = await _add_creator(
        db, cv_person_id=20, name="LateSeeded", followed=True, touched=False
    )
    await creators_unseed_startup_hook(_app_double(db))

    row = await _get(db, late)
    assert row.followed is True  # untouched — the one-shot fix did not re-run


@pytest.mark.req("FRG-CRTR-004")
async def test_unseed_runs_on_empty_library(db):
    """With no creators at all, the fix is a cheap no-op that still lays down the
    marker, so a later restart never re-runs it."""
    assert not await is_unseed_complete(db)
    await creators_unseed_startup_hook(_app_double(db))
    assert await is_unseed_complete(db)


@pytest.mark.req("FRG-CRTR-004")
async def test_unseed_hook_is_ordered_before_backfill(tmp_path: Path):
    """Startup ordering: the unseed hook is registered BEFORE the backfill hook,
    so a first-boot-after-upgrade can never seed-then-unseed within one start."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    app = create_app(make_settings(cfg))
    hooks = app.state.startup_hooks
    assert creators_unseed_startup_hook in hooks
    assert creators_backfill_startup_hook in hooks
    assert hooks.index(creators_unseed_startup_hook) < hooks.index(
        creators_backfill_startup_hook
    )
