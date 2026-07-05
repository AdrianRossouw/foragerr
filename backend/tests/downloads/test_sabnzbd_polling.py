"""FRG-DL-004 — SABnzbd queue/history polling, state mapping, category filter."""

from __future__ import annotations

import pytest

from foragerr.downloads.clients.base import ClientItemStatus
from downloads_support import (
    SabFixture,
    history_slot,
    make_sab_client,
    queue_slot,
)


def _by_id(items):
    return {item.download_id: item for item in items}


@pytest.mark.req("FRG-DL-004")
@pytest.mark.parametrize(
    "sab_status, expected",
    [
        ("Paused", ClientItemStatus.PAUSED),
        ("Queued", ClientItemStatus.QUEUED),
        ("Grabbing", ClientItemStatus.QUEUED),
        ("Propagating", ClientItemStatus.QUEUED),
        ("Downloading", ClientItemStatus.DOWNLOADING),
        ("Verifying", ClientItemStatus.DOWNLOADING),
        ("Extracting", ClientItemStatus.DOWNLOADING),
        ("Repairing", ClientItemStatus.DOWNLOADING),
    ],
)
async def test_queue_states_map_to_typed_statuses(tmp_path, db, sab_status, expected):
    fixture = SabFixture()
    fixture.queue_slots = [queue_slot(nzo_id="q1", status=sab_status)]
    client = make_sab_client(tmp_path, fixture, db)
    items = await client.get_items()
    assert items[0].status is expected


@pytest.mark.req("FRG-DL-004")
async def test_history_completed_and_failed_map(tmp_path, db):
    fixture = SabFixture()
    fixture.history_slots = [
        history_slot(nzo_id="done", status="Completed"),
        history_slot(nzo_id="bad", status="Failed", fail_message="Unpack failed"),
    ]
    client = make_sab_client(tmp_path, fixture, db)
    items = _by_id(await client.get_items())
    assert items["done"].status is ClientItemStatus.COMPLETED
    assert items["bad"].status is ClientItemStatus.FAILED
    assert items["bad"].reason == "Unpack failed"


@pytest.mark.req("FRG-DL-004")
async def test_disk_full_unpack_maps_to_warning_not_failed(tmp_path, db):
    fixture = SabFixture()
    fixture.history_slots = [
        history_slot(
            nzo_id="fullup",
            status="Failed",
            fail_message="Unpacking failed, write error or disk is full? No space left",
            storage="",
        )
    ]
    client = make_sab_client(tmp_path, fixture, db)
    item = (await client.get_items())[0]
    assert item.status is ClientItemStatus.WARNING


@pytest.mark.req("FRG-DL-004")
async def test_encrypted_history_item_is_failed_with_reason(tmp_path, db):
    fixture = SabFixture()
    fixture.history_slots = [
        history_slot(
            nzo_id="enc",
            name="ENCRYPTED/Saga 001",
            status="Failed",
            fail_message="Unpacking failed, archive requires a password",
            storage="",
        )
    ]
    client = make_sab_client(tmp_path, fixture, db)
    item = (await client.get_items())[0]
    assert item.status is ClientItemStatus.FAILED
    assert item.encrypted is True
    assert item.reason and "password" in item.reason.lower()


@pytest.mark.req("FRG-DL-004")
async def test_category_filter_excludes_other_categories(tmp_path, db):
    fixture = SabFixture()
    fixture.queue_slots = [
        queue_slot(nzo_id="mine", cat="comics"),
        queue_slot(nzo_id="theirs", cat="movies"),
    ]
    fixture.history_slots = [history_slot(nzo_id="mine_done", category="tv")]
    client = make_sab_client(tmp_path, fixture, db)
    ids = {item.download_id for item in await client.get_items()}
    assert ids == {"mine"}  # movies + tv never appear


@pytest.mark.req("FRG-DL-004")
async def test_star_item_category_is_not_hijacked_when_configured_for_comics(tmp_path, db):
    # SAB's default/uncategorized items report cat="*". A foragerr configured for
    # "comics" must NOT claim them (they belong to whatever queued them); the
    # wildcard is on the CONFIGURED side only.
    fixture = SabFixture()
    fixture.queue_slots = [
        queue_slot(nzo_id="mine", cat="comics"),
        queue_slot(nzo_id="uncategorized", cat="*"),
    ]
    client = make_sab_client(tmp_path, fixture, db)
    ids = {item.download_id for item in await client.get_items()}
    assert ids == {"mine"}  # the "*" item is not hijacked


@pytest.mark.req("FRG-DL-004")
async def test_configured_star_claims_every_category(tmp_path, db):
    from downloads_support import sab_settings

    fixture = SabFixture()
    fixture.queue_slots = [
        queue_slot(nzo_id="a", cat="comics"),
        queue_slot(nzo_id="b", cat="movies"),
    ]
    client = make_sab_client(
        tmp_path, fixture, db, settings_model=sab_settings(category="*")
    )
    ids = {item.download_id for item in await client.get_items()}
    assert ids == {"a", "b"}  # configured "*" claims all


@pytest.mark.req("FRG-DL-004")
async def test_sizes_normalized_to_bytes_and_time_parsed(tmp_path, db):
    fixture = SabFixture()
    fixture.queue_slots = [
        queue_slot(nzo_id="q", mb="50.0", mbleft="20.0", timeleft="0:01:30")
    ]
    fixture.history_slots = [history_slot(nzo_id="h", bytes_=52_428_800)]
    client = make_sab_client(tmp_path, fixture, db)
    items = _by_id(await client.get_items())
    assert items["q"].total_size == 50 * 1024 * 1024
    assert items["q"].remaining_size == 20 * 1024 * 1024
    assert items["q"].estimated_time == 90.0  # 1m30s
    assert items["h"].total_size == 52_428_800
    assert items["h"].remaining_size == 0  # completed


@pytest.mark.req("FRG-DL-004")
async def test_queue_and_history_are_merged(tmp_path, db):
    fixture = SabFixture()
    fixture.queue_slots = [queue_slot(nzo_id="q")]
    fixture.history_slots = [history_slot(nzo_id="h")]
    client = make_sab_client(tmp_path, fixture, db)
    ids = {item.download_id for item in await client.get_items()}
    assert ids == {"q", "h"}
