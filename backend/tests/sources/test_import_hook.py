"""Import-completion → entitlement + edition-reconcile hook (FRG-SRC-006/007).

The store grab hands a verified file to the shared import pipeline as a normal
completed download (``humble:{ent_id}``) and leaves the entitlement in
``import_pending``. Only when ``ProcessImportsCommand`` actually lands the file
does the entitlement advance to ``imported`` — and for a collected edition its
covered singles become owned-via-edition in the SAME import transaction.
"""

from __future__ import annotations

import datetime as dt
import os
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import select

from foragerr.downloads.imports import process_imports
from foragerr.downloads.models import GrabHistoryRow, TrackedDownloadRow
from foragerr.downloads.state import TRACKED_STATUS_OK, TrackedDownloadState
from foragerr.library import repo as library_repo
from foragerr.library.containment import RangeInput, replace_issue_collections
from foragerr.sources import repo
from foragerr.sources.import_hook import apply_source_import
from foragerr.sources.models import SourceEntitlementRow
from foragerr.sources.registry import TYPE_HUMBLE
from foragerr.sources.settings import HumbleSettings
from http_support import make_settings
from sources_support import (  # noqa: F401 — imported fixtures
    format_profile_id,
    root_folder_id,
)

_NOW = dt.datetime(2026, 7, 12, 12, 0, 0)

_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f9f0000000049454e44ae42"
    "6082"
)


def _make_cbz(path: Path, *, filler: int = 200 * 1024) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("page000.png", _PNG_1x1)
        zf.writestr("filler.bin", os.urandom(filler))


async def _entitlement(db, *, matched_series_id, download_state) -> int:
    source = await repo.create_source(
        db,
        source_type=TYPE_HUMBLE,
        name="Humble Bundle",
        settings=HumbleSettings(session_cookie="SYNTH-COOKIE"),
        connection_state="connected",
    )
    now = _NOW
    async with db.write_session() as session:
        row = SourceEntitlementRow(
            source_id=source.id,
            gamekey="gk",
            machine_name="mn",
            human_name="Synthetic Hero #1",
            publisher=None,
            classification="comic",
            review_status="matched",
            download_state=download_state,
            matched_series_id=matched_series_id,
            md5="a" * 32,
            file_size=1,
            filename="synthetic.cbz",
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        return row.id


async def _tracked(
    db, *, download_id, series_id, output_path, title="Synthetic Hero #1"
) -> None:
    now = _NOW
    async with db.write_session() as session:
        session.add(
            GrabHistoryRow(
                download_id=download_id,
                client_id=None,
                series_id=series_id,
                issue_id=None,
                title=title,
                protocol="humble",
                source="store",
                created_at=now,
            )
        )
        session.add(
            TrackedDownloadRow(
                download_id=download_id,
                client_id=None,
                client_name="Humble Bundle",
                protocol="humble",
                source="store",
                state=TrackedDownloadState.IMPORT_PENDING.value,
                status=TRACKED_STATUS_OK,
                series_id=series_id,
                issue_id=None,
                title=title,
                output_path=output_path,
                encrypted=False,
                added_at=now,
                updated_at=now,
            )
        )


# --- B1/B5 wiring: the drain advances the entitlement to imported ------------


@pytest.mark.req("FRG-SRC-006")
async def test_drain_advances_entitlement_only_on_durable_import(
    db, config_dir, format_profile_id, tmp_path
):
    root = tmp_path / "lib-root"
    root.mkdir(exist_ok=True)
    async with db.write_session() as session:
        rf = await library_repo.create_root_folder(session, str(root))
        series = await library_repo.create_series(
            session,
            cv_volume_id=987654,
            title="Spawn",
            start_year=2024,
            format_profile_id=format_profile_id,
            root_folder_id=rf.id,
            path=str(root / "Spawn"),
            monitored=True,
        )
        await session.flush()
        issue = await library_repo.create_issue(
            session,
            series_id=series.id,
            cv_issue_id=123456,
            issue_number="1",
            cover_date=dt.date(2024, 1, 1),
            monitored=True,
        )
        series_id, issue_id = series.id, issue.id

    eid = await _entitlement(
        db, matched_series_id=series_id, download_state="import_pending"
    )
    dl_dir = tmp_path / "downloads" / "Spawn.001.2024"
    _make_cbz(dl_dir / "Spawn 001 (2024).cbz")
    await _tracked(
        db,
        download_id=f"humble:{eid}",
        series_id=series_id,
        output_path=str(dl_dir),
        title="Spawn 001 (2024)",
    )

    summary = await process_imports(db, make_settings(config_dir), now=_NOW)
    assert summary == "imported=1 blocked=0 failed=0"

    # Only now — after the file is durably in the library — is the entitlement
    # marked imported (never claimed early at handoff).
    ent = await repo.get_entitlement(db, eid)
    assert ent.download_state == "imported"
    assert ent.download_error is None
    _ = issue_id


# --- B5 reconcile: an imported collected edition fills its singles -----------


@pytest.mark.req("FRG-SRC-007")
async def test_import_hook_reconciles_collected_edition_atomically(
    db, config_dir, root_folder_id, format_profile_id
):
    # A singles run of 3 file-less released issues + a trade collecting them.
    async with db.write_session() as session:
        run = await library_repo.create_series(
            session,
            cv_volume_id=100,
            title="Synthetic Hero",
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path="/tmp/comics/run",
        )
        single_ids = []
        for i in range(1, 4):
            iss = await library_repo.create_issue(
                session,
                series_id=run.id,
                cv_issue_id=100 * 10 + i,
                issue_number=str(i),
                monitored=True,
            )
            single_ids.append(iss.id)
        trade = await library_repo.create_series(
            session,
            cv_volume_id=200,
            title="Synthetic Hero HC",
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path="/tmp/comics/trade",
        )
        trade.booktype = "tpb"  # containment can only be declared on a trade
        trade_issue = await library_repo.create_issue(
            session,
            series_id=trade.id,
            cv_issue_id=200 * 10 + 1,
            issue_number="1",
            monitored=True,
        )
        run_id, trade_id, trade_issue_id = run.id, trade.id, trade_issue.id
    async with db.write_session() as session:
        await replace_issue_collections(
            session,
            trade_issue_id,
            [
                RangeInput(
                    target_series_id=run_id,
                    start_issue_id=single_ids[0],
                    end_issue_id=single_ids[2],
                )
            ],
        )

    eid = await _entitlement(
        db, matched_series_id=trade_id, download_state="import_pending"
    )

    # Simulate the import terminal transition the drain performs: the trade issue
    # imported to a real file, and the hook runs in that same transaction.
    async with db.write_session() as session:
        # The trade's own imported file.
        await library_repo.add_issue_file(
            session, issue_id=trade_issue_id, path="/tmp/comics/trade/hc.cbz", size=250_000
        )
        await apply_source_import(
            session,
            download_id=f"humble:{eid}",
            final_state=TrackedDownloadState.IMPORTED,
            imported_issues=[(trade_issue_id, "/tmp/comics/trade/hc.cbz")],
            now=_NOW,
        )

    ent = await repo.get_entitlement(db, eid)
    assert ent.download_state == "imported"
    # The three covered singles are now owned-via-edition → none wanted.
    async with db.read_session() as session:
        wanted = set(await library_repo.wanted_issue_ids(session))
    assert not (set(single_ids) & wanted)


@pytest.mark.req("FRG-SRC-006")
async def test_import_hook_mirrors_blocked_and_failed(db, config_dir):
    eid_blocked = await _entitlement(
        db, matched_series_id=None, download_state="import_pending"
    )
    eid_failed = await _entitlement(
        db, matched_series_id=None, download_state="import_pending"
    )
    async with db.write_session() as session:
        await apply_source_import(
            session,
            download_id=f"humble:{eid_blocked}",
            final_state=TrackedDownloadState.IMPORT_BLOCKED,
            imported_issues=[],
            now=_NOW,
        )
        await apply_source_import(
            session,
            download_id=f"humble:{eid_failed}",
            final_state=TrackedDownloadState.FAILED_PENDING,
            imported_issues=[],
            now=_NOW,
        )
    assert (await repo.get_entitlement(db, eid_blocked)).download_state == "import_blocked"
    failed = await repo.get_entitlement(db, eid_failed)
    assert failed.download_state == "failed"
    assert failed.download_error


# --- ignore-mid-import race: the hook's review_status re-read guard ----------


@pytest.mark.req("FRG-SRC-007")
async def test_ignored_mid_import_claims_no_ownership(
    db, config_dir, root_folder_id, format_profile_id
):
    """Ignore lands while the drain already claimed the completed download: the
    hook re-reads ``review_status`` and discards the entitlement mirror + edition
    reconcile — the ignored trade never claims ownership, its covered singles
    stay wanted, and the download axis stays as the ignore reset it."""
    async with db.write_session() as session:
        run = await library_repo.create_series(
            session,
            cv_volume_id=300,
            title="Synthetic Hero",
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path="/tmp/comics/run-ignored",
        )
        single_ids = []
        for i in range(1, 4):
            iss = await library_repo.create_issue(
                session,
                series_id=run.id,
                cv_issue_id=300 * 10 + i,
                issue_number=str(i),
                monitored=True,
            )
            single_ids.append(iss.id)
        trade = await library_repo.create_series(
            session,
            cv_volume_id=400,
            title="Synthetic Hero HC",
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path="/tmp/comics/trade-ignored",
        )
        trade.booktype = "tpb"
        trade_issue = await library_repo.create_issue(
            session,
            series_id=trade.id,
            cv_issue_id=400 * 10 + 1,
            issue_number="1",
            monitored=True,
        )
        run_id, trade_id, trade_issue_id = run.id, trade.id, trade_issue.id
    async with db.write_session() as session:
        await replace_issue_collections(
            session,
            trade_issue_id,
            [
                RangeInput(
                    target_series_id=run_id,
                    start_issue_id=single_ids[0],
                    end_issue_id=single_ids[2],
                )
            ],
        )

    eid = await _entitlement(
        db, matched_series_id=trade_id, download_state="import_pending"
    )
    # The operator's ignore landed first: review reset the download axis.
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, eid)
        row.review_status = "ignored"
        row.download_state = None

    # The already-claimed import still terminates; the hook must discard it.
    async with db.write_session() as session:
        await library_repo.add_issue_file(
            session,
            issue_id=trade_issue_id,
            path="/tmp/comics/trade-ignored/hc.cbz",
            size=250_000,
        )
        await apply_source_import(
            session,
            download_id=f"humble:{eid}",
            final_state=TrackedDownloadState.IMPORTED,
            imported_issues=[(trade_issue_id, "/tmp/comics/trade-ignored/hc.cbz")],
            now=_NOW,
        )

    ent = await repo.get_entitlement(db, eid)
    assert ent.review_status == "ignored"
    assert ent.download_state is None  # never resurrected to "imported"
    # No owned-via-edition fills: all three covered singles remain wanted.
    async with db.read_session() as session:
        wanted = set(await library_repo.wanted_issue_ids(session))
    assert set(single_ids) <= wanted


@pytest.mark.req("FRG-SRC-006")
async def test_blocked_or_failed_import_never_resurrects_ignored_axis(db, config_dir):
    """The guard covers the non-success mirrors too: a block/fail terminal for an
    ignored entitlement must not push it back onto the download axis."""
    eid = await _entitlement(db, matched_series_id=None, download_state="import_pending")
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, eid)
        row.review_status = "ignored"
        row.download_state = None
    async with db.write_session() as session:
        await apply_source_import(
            session,
            download_id=f"humble:{eid}",
            final_state=TrackedDownloadState.IMPORT_BLOCKED,
            imported_issues=[],
            now=_NOW,
        )
    ent = await repo.get_entitlement(db, eid)
    assert ent.download_state is None
    assert ent.review_status == "ignored"
