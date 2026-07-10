"""HTTP contract tests for trade containment (FRG-API-022).

Covers the three surfaces: the per-series issues listing carrying collected-in
chips, the per-series collections rollup with request-time coverage, and the
declare/replace/delete write endpoints with the standard error shape. Writes
touch only containment rows — no issue/series/file/wanted mutation.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flows_support import flows_settings
from foragerr.app import create_app
from foragerr.library import repo


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return flows_settings(cfg)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


async def _seed(app, root: Path) -> dict:
    """A target single-issues series #1..#6 (#1–#3 owned) and two trade issues:
    one collecting #1–#3 (fully owned), one collecting #1–#6 (partial)."""
    root.mkdir(exist_ok=True)
    db = app.state.db
    from sqlalchemy import select

    from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow

    ids: dict = {}
    async with db.write_session() as session:
        root_row = await repo.create_root_folder(session, str(root))
        profile_id = await session.scalar(
            select(FormatProfileRow.id).where(
                FormatProfileRow.name == DEFAULT_PROFILE_NAME
            )
        )

        target = await repo.create_series(
            session,
            cv_volume_id=1,
            title="Saga",
            format_profile_id=profile_id,
            root_folder_id=root_row.id,
            path="/lib/Saga",
        )
        ids["target_id"] = target.id
        ids["issues"] = {}
        for n in range(1, 7):
            iss = await repo.create_issue(
                session,
                series_id=target.id,
                cv_issue_id=1000 + n,
                issue_number=str(n),
            )
            ids["issues"][str(n)] = iss.id
            if n <= 3:
                await repo.add_issue_file(
                    session, issue_id=iss.id, path=f"/lib/Saga/{n}.cbz", size=100
                )

        async def make_trade(cv, title):
            s = await repo.create_series(
                session,
                cv_volume_id=cv,
                title=title,
                format_profile_id=profile_id,
                root_folder_id=root_row.id,
                path=f"/lib/{title}",
            )
            s.booktype = "tpb"
            ti = await repo.create_issue(
                session,
                series_id=s.id,
                cv_issue_id=cv * 10,
                issue_number="1",
                cover_date=dt.date(2020, 5, 1),
            )
            await session.flush()
            return s.id, ti.id

        ids["collected_series"], ids["collected_trade"] = await make_trade(2, "Saga Vol 1 TPB")
        ids["partial_series"], ids["partial_trade"] = await make_trade(3, "Saga Deluxe HC")
    return ids


@pytest.mark.req("FRG-API-022")
def test_issues_listing_carries_collected_in_chips(client, tmp_path):
    ids = client.portal.call(_seed, client.app, tmp_path / "lib")
    # Declare: collected_trade collects #1–#3.
    resp = client.put(
        f"/api/v1/issues/{ids['collected_trade']}/collections",
        json={
            "ranges": [
                {
                    "target_series_id": ids["target_id"],
                    "start_issue_id": ids["issues"]["1"],
                    "end_issue_id": ids["issues"]["3"],
                }
            ]
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "trade_issue_id": ids["collected_trade"],
        "ranges": [{"target_series_id": ids["target_id"], "range_label": "#1–#3"}],
    }

    listing = client.get("/api/v1/issues", params={"seriesId": ids["target_id"], "pageSize": 50})
    assert listing.status_code == 200
    by_num = {rec["issue_number"]: rec for rec in listing.json()["records"]}
    # Exactly #1–#3 carry the chip; #4–#6 carry an empty list.
    for n in ("1", "2", "3"):
        chips = by_num[n]["collected_in"]
        assert len(chips) == 1
        assert chips[0]["trade_series_id"] == ids["collected_series"]
        assert chips[0]["trade_issue_id"] == ids["collected_trade"]
        assert chips[0]["booktype"] == "tpb"
        assert chips[0]["range_label"] == "#1–#3"
    for n in ("4", "5", "6"):
        assert by_num[n]["collected_in"] == []


@pytest.mark.req("FRG-API-022")
def test_collections_rollup_with_coverage(client, tmp_path):
    ids = client.portal.call(_seed, client.app, tmp_path / "lib")
    client.put(
        f"/api/v1/issues/{ids['collected_trade']}/collections",
        json={"ranges": [{"target_series_id": ids["target_id"],
                          "start_issue_id": ids["issues"]["1"],
                          "end_issue_id": ids["issues"]["3"]}]},
    )
    client.put(
        f"/api/v1/issues/{ids['partial_trade']}/collections",
        json={"ranges": [{"target_series_id": ids["target_id"],
                          "start_issue_id": ids["issues"]["1"],
                          "end_issue_id": ids["issues"]["6"]}]},
    )

    resp = client.get(f"/api/v1/series/{ids['target_id']}/collections")
    assert resp.status_code == 200
    records = {r["trade_issue_id"]: r for r in resp.json()["records"]}

    collected = records[ids["collected_trade"]]
    assert collected["coverage"] == "collected"
    assert collected["issues_in_ranges"] == 3 and collected["owned_in_ranges"] == 3
    assert collected["trade_series_id"] == ids["collected_series"]
    assert collected["booktype"] == "tpb"
    assert collected["release_date"] == "2020-05-01"
    assert collected["ranges"] == [
        {
            "target_series_id": ids["target_id"],
            "label": "#1–#3",
            "start_issue_id": ids["issues"]["1"],
            "end_issue_id": ids["issues"]["3"],
        }
    ]

    partial = records[ids["partial_trade"]]
    assert partial["coverage"] == "partial"
    assert partial["issues_in_ranges"] == 6 and partial["owned_in_ranges"] == 3


@pytest.mark.req("FRG-API-022")
def test_collections_rollup_none_when_no_files(client, tmp_path):
    ids = client.portal.call(_seed, client.app, tmp_path / "lib")
    # #4–#6 have no files.
    client.put(
        f"/api/v1/issues/{ids['collected_trade']}/collections",
        json={"ranges": [{"target_series_id": ids["target_id"],
                          "start_issue_id": ids["issues"]["4"],
                          "end_issue_id": ids["issues"]["6"]}]},
    )
    resp = client.get(f"/api/v1/series/{ids['target_id']}/collections")
    rec = {r["trade_issue_id"]: r for r in resp.json()["records"]}[ids["collected_trade"]]
    assert rec["coverage"] == "none"
    assert rec["owned_in_ranges"] == 0


@pytest.mark.req("FRG-API-022")
def test_declaration_validation_uses_standard_error_shape(client, tmp_path):
    ids = client.portal.call(_seed, client.app, tmp_path / "lib")

    # Endpoint issue from the wrong series -> 400 naming the field.
    resp = client.put(
        f"/api/v1/issues/{ids['collected_trade']}/collections",
        json={"ranges": [{"target_series_id": ids["target_id"],
                          "start_issue_id": ids["issues"]["1"],
                          "end_issue_id": ids["collected_trade"]}]},  # wrong series
    )
    assert resp.status_code == 400
    body = resp.json()
    assert set(body) == {"message", "errors"}
    assert body["errors"] and body["errors"][0]["field"] == "end_issue_id"

    # Bounds out of order.
    resp = client.put(
        f"/api/v1/issues/{ids['collected_trade']}/collections",
        json={"ranges": [{"target_series_id": ids["target_id"],
                          "start_issue_id": ids["issues"]["6"],
                          "end_issue_id": ids["issues"]["1"]}]},
    )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "end_issue_id"

    # A single-issues (non-trade) issue cannot host containment -> 400.
    resp = client.put(
        f"/api/v1/issues/{ids['issues']['1']}/collections",
        json={"ranges": [{"target_series_id": ids["target_id"],
                          "start_issue_id": ids["issues"]["1"],
                          "end_issue_id": ids["issues"]["2"]}]},
    )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "issue_id"

    # Nothing was written by any rejected call.
    assert client.get(f"/api/v1/series/{ids['target_id']}/collections").json()["records"] == []


@pytest.mark.req("FRG-API-022")
def test_declaration_unknown_target_series_is_400(client, tmp_path):
    ids = client.portal.call(_seed, client.app, tmp_path / "lib")
    resp = client.put(
        f"/api/v1/issues/{ids['collected_trade']}/collections",
        json={"ranges": [{"target_series_id": 999999,
                          "start_issue_id": ids["issues"]["1"],
                          "end_issue_id": ids["issues"]["3"]}]},
    )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "target_series_id"
    assert client.get(f"/api/v1/series/{ids['target_id']}/collections").json()["records"] == []


@pytest.mark.req("FRG-API-022")
def test_declaration_self_containment_is_400(client, tmp_path):
    ids = client.portal.call(_seed, client.app, tmp_path / "lib")
    # Target the trade issue's OWN series (endpoints = the trade issue itself,
    # which belongs to that series) -> self-containment, field-precise 400.
    resp = client.put(
        f"/api/v1/issues/{ids['collected_trade']}/collections",
        json={"ranges": [{"target_series_id": ids["collected_series"],
                          "start_issue_id": ids["collected_trade"],
                          "end_issue_id": ids["collected_trade"]}]},
    )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "target_series_id"


@pytest.mark.req("FRG-API-022")
def test_declaration_ranges_cap_is_400(client, tmp_path):
    ids = client.portal.call(_seed, client.app, tmp_path / "lib")
    # More than the 100-range cap -> rejected at the request-validation layer,
    # mapped to the uniform 400 shape (the app maps RequestValidationError -> 400).
    too_many = [
        {"target_series_id": ids["target_id"],
         "start_issue_id": ids["issues"]["1"],
         "end_issue_id": ids["issues"]["1"]}
        for _ in range(101)
    ]
    resp = client.put(
        f"/api/v1/issues/{ids['collected_trade']}/collections",
        json={"ranges": too_many},
    )
    assert resp.status_code == 400
    assert set(resp.json()) == {"message", "errors"}


@pytest.mark.req("FRG-API-022")
def test_collections_both_directions_over_http(client, tmp_path):
    """The trade's OWN collections read (direction B) surfaces its issue's
    declaration with resolved endpoint issue ids, so the edit dialog can
    pre-fill."""
    ids = client.portal.call(_seed, client.app, tmp_path / "lib")
    client.put(
        f"/api/v1/issues/{ids['collected_trade']}/collections",
        json={"ranges": [{"target_series_id": ids["target_id"],
                          "start_issue_id": ids["issues"]["1"],
                          "end_issue_id": ids["issues"]["3"]}]},
    )

    # Direction B: read the TRADE series' own collections.
    resp = client.get(f"/api/v1/series/{ids['collected_series']}/collections")
    assert resp.status_code == 200
    records = resp.json()["records"]
    assert len(records) == 1
    rec = records[0]
    assert rec["trade_issue_id"] == ids["collected_trade"]
    assert rec["coverage"] == "collected"
    assert rec["ranges"] == [
        {
            "target_series_id": ids["target_id"],
            "label": "#1–#3",
            "start_issue_id": ids["issues"]["1"],
            "end_issue_id": ids["issues"]["3"],
        }
    ]


@pytest.mark.req("FRG-API-022")
def test_writes_are_containment_only(client, tmp_path):
    ids = client.portal.call(_seed, client.app, tmp_path / "lib")

    def wanted_ids():
        return {r["id"] for r in client.get(
            "/api/v1/wanted/missing", params={"pageSize": 200}
        ).json()["records"]}

    before = wanted_ids()
    series_before = client.get(f"/api/v1/series/{ids['target_id']}").json()

    client.put(
        f"/api/v1/issues/{ids['collected_trade']}/collections",
        json={"ranges": [{"target_series_id": ids["target_id"],
                          "start_issue_id": ids["issues"]["1"],
                          "end_issue_id": ids["issues"]["3"]}]},
    )
    assert wanted_ids() == before
    assert client.get(f"/api/v1/series/{ids['target_id']}").json() == series_before

    # DELETE clears and is idempotent; still no wanted/series drift.
    assert client.delete(f"/api/v1/issues/{ids['collected_trade']}/collections").status_code == 204
    assert client.delete(f"/api/v1/issues/{ids['collected_trade']}/collections").status_code == 204
    assert client.get(f"/api/v1/series/{ids['target_id']}/collections").json()["records"] == []
    assert wanted_ids() == before


@pytest.mark.req("FRG-API-022")
def test_collections_for_missing_series_is_404(client, tmp_path):
    client.portal.call(_seed, client.app, tmp_path / "lib")
    assert client.get("/api/v1/series/999999/collections").status_code == 404
