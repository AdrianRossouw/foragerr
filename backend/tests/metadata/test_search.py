"""Series search: plausibility annotations, publisher ignore-list, bounded
truncation (FRG-META-007)."""

from __future__ import annotations

import logging

import httpx
import pytest

from cv_support import _reset_gate, json_response, make_client  # noqa: F401
from fixtures import search_envelope, volume_payload


def _volumes():
    return [
        volume_payload(id=1, name="Saga", publisher={"name": "Image Comics"},
                       start_year="2012", issues=[{"id": 1}] * 60),
        volume_payload(id=2, name="Saga of the Swamp Thing",
                       publisher={"name": "DC Comics"}, start_year="1985",
                       issues=[{"id": 1}] * 171),
        volume_payload(id=3, name="Saga Variant Reprints",
                       publisher={"name": "Reprint House"}, start_year="2020",
                       issues=[{"id": 1}] * 3),
    ]


@pytest.mark.req("FRG-META-007")
async def test_candidates_annotated_no_auto_pick(tmp_path):
    client, _ = make_client(
        tmp_path,
        lambda r: json_response(search_envelope(_volumes(), total=3)),
        comicvine_min_interval_seconds=0.05,
    )
    async with client:
        result = await client.search_series("Saga 2012")

    # returns a candidate LIST, does not select one
    assert len(result.candidates) >= 2
    by_id = {c.series.cv_volume_id: c for c in result.candidates}
    exact = by_id[1]
    swamp = by_id[2]
    assert exact.plausibility.year_proximity == 0  # 2012 vs query year 2012
    assert swamp.plausibility.year_proximity == 27  # 1985 vs 2012
    assert exact.plausibility.name_similarity > swamp.plausibility.name_similarity
    assert exact.plausibility.haveit is False  # library flag left to the caller


@pytest.mark.req("FRG-META-007")
async def test_ignored_publisher_excluded_others_only_annotated(tmp_path):
    client, _ = make_client(
        tmp_path,
        lambda r: json_response(search_envelope(_volumes(), total=3)),
        comicvine_ignored_publishers="Reprint House, Some Other Imprint",
        comicvine_min_interval_seconds=0.05,
    )
    async with client:
        result = await client.search_series("Saga")
    ids = {c.series.cv_volume_id for c in result.candidates}
    assert 3 not in ids  # ignored-publisher volume hard-dropped
    assert {1, 2} <= ids  # the rest survive, merely annotated


@pytest.mark.req("FRG-META-007")
async def test_target_issue_plausibility_annotation(tmp_path):
    client, _ = make_client(
        tmp_path,
        lambda r: json_response(search_envelope(_volumes(), total=3)),
        comicvine_min_interval_seconds=0.05,
    )
    async with client:
        result = await client.search_series("Saga", target_issue="150")
    by_id = {c.series.cv_volume_id: c for c in result.candidates}
    assert by_id[1].plausibility.target_issue_plausible is False  # only 60 issues
    assert by_id[2].plausibility.target_issue_plausible is True  # 171 issues


@pytest.mark.req("FRG-META-007")
async def test_bounded_result_cap_with_truncation_warning(tmp_path, caplog):
    client, _ = make_client(
        tmp_path,
        lambda r: json_response(search_envelope(_volumes(), total=3)),
        comicvine_search_result_cap=2,
        comicvine_min_interval_seconds=0.05,
    )
    with caplog.at_level(logging.WARNING, logger="foragerr.metadata.comicvine"):
        async with client:
            result = await client.search_series("Saga")
    assert result.truncated is True
    assert len(result.candidates) <= 2
    assert any("truncat" in r.getMessage().lower() for r in caplog.records)
