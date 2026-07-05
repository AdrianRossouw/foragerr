"""FRG-DL-005 — remote path mapping: rewrite completed paths, warn when foreign."""

from __future__ import annotations

import pytest

from foragerr.downloads.clients.base import ClientItemStatus
from foragerr.downloads.pathmap import (
    CHECK_MAPPING_WARNING,
    RemotePathMapping,
    apply_mappings,
)
from downloads_support import SabFixture, history_slot, make_sab_client


@pytest.mark.req("FRG-DL-005")
def test_mapping_rewrites_a_matching_remote_prefix():
    mappings = [RemotePathMapping("sab", "/downloads/complete", "/library/incoming")]
    result = apply_mappings("/downloads/complete/Saga/001.cbz", mappings)
    assert result.path == "/library/incoming/Saga/001.cbz"
    assert result.warning is None


@pytest.mark.req("FRG-DL-005")
def test_windows_remote_prefix_rewrites_to_local():
    mappings = [RemotePathMapping("sab", "C:\\downloads", "/library/incoming")]
    result = apply_mappings("C:\\downloads\\Saga\\001.cbz", mappings)
    assert result.path == "/library/incoming/Saga/001.cbz"
    assert result.warning is None


@pytest.mark.req("FRG-DL-005")
def test_unmapped_foreign_windows_path_warns_not_silent():
    result = apply_mappings("D:\\media\\Saga\\001.cbz", mappings=[])
    assert result.warning == CHECK_MAPPING_WARNING
    assert result.path == "D:\\media\\Saga\\001.cbz"  # unchanged, surfaced


@pytest.mark.req("FRG-DL-005")
def test_configured_but_unmatched_mapping_warns():
    mappings = [RemotePathMapping("sab", "/downloads/complete", "/library/incoming")]
    result = apply_mappings("/other/place/Saga/001.cbz", mappings)
    assert result.warning == CHECK_MAPPING_WARNING


@pytest.mark.req("FRG-DL-005")
def test_plain_local_path_with_no_mappings_is_not_flagged():
    result = apply_mappings("/downloads/complete/Saga/001.cbz", mappings=[])
    assert result.warning is None


@pytest.mark.req("FRG-DL-005")
async def test_completed_item_path_is_rewritten_by_mappings(tmp_path, db):
    fixture = SabFixture()
    fixture.history_slots = [
        history_slot(nzo_id="done", storage="/remote/complete/Saga 001")
    ]
    client = make_sab_client(
        tmp_path,
        fixture,
        db,
        mappings=[RemotePathMapping("sab", "/remote/complete", "/library/in")],
    )
    item = (await client.get_items())[0]
    assert item.output_path == "/library/in/Saga 001"
    assert item.status is ClientItemStatus.COMPLETED


@pytest.mark.req("FRG-DL-005")
async def test_completed_item_foreign_path_becomes_a_warning(tmp_path, db):
    fixture = SabFixture()
    fixture.history_slots = [
        history_slot(nzo_id="done", storage="/remote/complete/Saga 001")
    ]
    # A mapping is configured for the client but does not match this path:
    # the item is surfaced as a warning rather than a silent import failure.
    client = make_sab_client(
        tmp_path,
        fixture,
        db,
        mappings=[RemotePathMapping("sab", "/elsewhere", "/library/in")],
    )
    item = (await client.get_items())[0]
    assert item.status is ClientItemStatus.WARNING
    assert item.reason == CHECK_MAPPING_WARNING
