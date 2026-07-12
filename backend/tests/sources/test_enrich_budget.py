"""Budget-deferred proposals stay retryable (FRG-SRC-004).

When ComicVine's per-path budget is exhausted mid-enrich, an item whose only
library candidate is WEAK must NOT be frozen with that weak library guess — doing
so would exclude it from the pending set forever and the deferred CV lookup would
never run. It is left NULL/retryable and picks up its CV match on the next sync.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from foragerr.db.base import utcnow
from foragerr.library import repo as library_repo
from foragerr.metadata.errors import ComicVineBudgetExhausted
from foragerr.sources import repo
from foragerr.sources.enrich import enrich_source
from foragerr.sources.models import SourceEntitlementRow
from foragerr.sources.registry import TYPE_HUMBLE
from foragerr.sources.settings import HumbleSettings
from http_support import make_settings
from sources_support import (  # noqa: F401 — imported fixtures
    format_profile_id,
    root_folder_id,
)


class _FakeCV:
    def __init__(self, candidates=None, *, raises=None):
        self._candidates = candidates or []
        self._raises = raises
        self.calls = 0

    async def suggest_series(self, term):
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return SimpleNamespace(candidates=self._candidates)

    async def aclose(self):
        pass


def _cand(cvid, name, year=None):
    return SimpleNamespace(cv_volume_id=cvid, name=name, start_year=year)


async def _new_comic(db, source_id, human_name) -> int:
    now = utcnow()
    async with db.write_session() as session:
        row = SourceEntitlementRow(
            source_id=source_id,
            gamekey="gk",
            machine_name="mn",
            human_name=human_name,
            publisher=None,
            classification="comic",
            review_status="new",
            download_state=None,
            md5="a" * 32,
            file_size=1,
            filename="x.cbz",
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        return row.id


@pytest.mark.req("FRG-SRC-004")
async def test_budget_exhausted_weak_library_item_is_retried_next_sync(
    db, config_dir, root_folder_id, format_profile_id
):
    source = await repo.create_source(
        db,
        source_type=TYPE_HUMBLE,
        name="Humble",
        settings=HumbleSettings(session_cookie="C"),
        connection_state="connected",
    )
    # A weak-only library candidate (~0.39 vs the entitlement title) so the
    # ranker must consult CV — where the budget will be exhausted.
    async with db.write_session() as session:
        await library_repo.create_series(
            session,
            cv_volume_id=42,
            title="Detective Comics Weekly",
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path="/tmp/comics/dcw",
        )
    eid = await _new_comic(db, source.id, "Obscure Chronicles #1")
    settings = make_settings(config_dir)

    # First sync: CV budget exhausted → the weak library guess is NOT frozen.
    await enrich_source(
        db,
        settings,
        source,
        cv_client=_FakeCV(raises=ComicVineBudgetExhausted("volume", retry_after_seconds=60)),
    )
    after_first = await repo.get_entitlement(db, eid)
    assert after_first.proposed_match_json is None  # left retryable, not stamped

    # Next sync: budget recovered → the deferred CV lookup runs and a match lands.
    await enrich_source(
        db,
        settings,
        source,
        cv_client=_FakeCV(candidates=[_cand(777, "Obscure Chronicles", 2015)]),
    )
    after_second = await repo.get_entitlement(db, eid)
    assert after_second.proposed_match_json is not None
    assert '"cv_volume_id": 777' in after_second.proposed_match_json
