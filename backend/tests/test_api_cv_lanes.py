"""Every API-layer ComicVine client runs in the INTERACTIVE lane (FRG-META-022).

The lane is declared once, where the client is CONSTRUCTED (design D2), which
makes the set of interactive construction sites the whole contract — and a set
is exactly the kind of thing that silently loses a member. The default is
``batch``, so a forgotten tag is invisible in behaviour until the night an
operator's search is refused while a background job spends the last of the
budget. These tests enumerate the API-layer sites and pin each one.

The recorder wraps ``ComicVineClient.__init__`` rather than asserting on source
text, so a site that stops going through the client (or starts building a second
one) fails here too.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from flows_support import flows_settings
from foragerr.app import create_app
from foragerr.metadata.comicvine import ComicVineClient
from foragerr.metadata.models import SearchResult, SeriesRecord, SuggestResult
from foragerr.metadata.ratelimit import LANE_INTERACTIVE


@pytest.fixture(autouse=True)
def _reset_gate():
    from foragerr.metadata import ratelimit

    ratelimit.reset_gate()
    yield
    ratelimit.reset_gate()


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return flows_settings(cfg)


@pytest.fixture
def lanes(monkeypatch) -> list[str]:
    """Every lane a ``ComicVineClient`` is constructed with during a test."""
    seen: list[str] = []
    original = ComicVineClient.__init__

    def recording_init(self, settings, factory, **kwargs):
        original(self, settings, factory, **kwargs)
        seen.append(self._lane)

    monkeypatch.setattr(ComicVineClient, "__init__", recording_init)
    return seen


def _returns(result):
    """A stub coroutine method that answers with ``result`` and never goes out."""

    async def fake(self, *args, **kwargs):
        return result

    return fake


@pytest.mark.req("FRG-META-022")
def test_series_lookup_and_suggest_run_interactive(settings, lanes, monkeypatch):
    """The operator is literally typing: lookup and suggest spend from the full
    path budget, not the batch share."""
    monkeypatch.setattr(
        ComicVineClient,
        "search_series",
        _returns(
            SearchResult(
                candidates=(), total_results=0, truncated=False, complete=True
            )
        ),
    )
    monkeypatch.setattr(
        ComicVineClient,
        "suggest_series",
        _returns(SuggestResult(candidates=(), complete=True)),
    )
    with TestClient(create_app(settings)) as client:
        lookup = client.get("/api/v1/series/lookup", params={"term": "Saga"})
        suggest = client.get("/api/v1/series/lookup/suggest", params={"term": "Saga"})
    assert lookup.status_code == 200 and suggest.status_code == 200

    assert lanes == [LANE_INTERACTIVE, LANE_INTERACTIVE]


@pytest.mark.req("FRG-META-022")
async def test_library_import_volume_validation_runs_interactive(
    settings, lanes, monkeypatch
):
    """An operator overriding an import group's volume is waiting on the answer."""
    from foragerr.api.library_import import _validate_cv_volume

    record = SeriesRecord(
        cv_volume_id=202,
        name="Paper Girls",
        publisher=None,
        imprint=None,
        start_year=None,
        count_of_issues=None,
        aliases=(),
        description=None,
        site_url=None,
        first_issue=None,
        image_url=None,
    )
    monkeypatch.setattr(ComicVineClient, "get_volume", _returns(record))
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings))
    )

    assert (await _validate_cv_volume(request, 202)).cv_volume_id == 202
    assert lanes == [LANE_INTERACTIVE]


@pytest.mark.req("FRG-META-022")
def test_comicvine_connectivity_test_runs_interactive(settings, lanes, monkeypatch):
    """The Test button must answer "is this key good?" — a paused batch lane
    would otherwise make a perfectly good key look broken."""
    monkeypatch.setattr(
        ComicVineClient,
        "suggest_series",
        _returns(SuggestResult(candidates=(), complete=True)),
    )
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/config/comicvine/test")

    assert response.status_code in (200, 400)  # outcome is this test's non-concern
    assert lanes == [LANE_INTERACTIVE]


@pytest.mark.req("FRG-META-022")
async def test_operator_source_actions_run_interactive(settings, lanes):
    """Restore / bulk restore on the review screen: the operator is watching the
    row they just clicked (FRG-SRC-010's operator paths)."""
    from foragerr.api.sources import _operator_cv_client

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings))
    )
    async with _operator_cv_client(request) as (client, configured):
        assert configured is True
        assert client is not None

    assert lanes == [LANE_INTERACTIVE]
