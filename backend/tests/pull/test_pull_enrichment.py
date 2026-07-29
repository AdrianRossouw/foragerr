"""Pull payload enrichment ingestion (FRG-PULL-011).

The source payload carries far more than the six fields the store used to keep:
a cover list, a description, credits, characters, and a UPC. These are display
only — nothing here feeds matching — but the cover URL is a *fetch target*, so
ingest validates it fail-closed against the same allowlist the cover proxy
enforces and stores it canonicalized (query and fragment dropped) so the
source's volatile cache-buster cannot break per-week idempotency.

Series/creator/character names throughout are invented for the fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from foragerr.api.pull import _characters, _creators, _decode_list
from foragerr.http import HttpClientFactory
from foragerr.pull import repo
from foragerr.pull.source import (
    MAX_DESCRIPTION_LENGTH,
    MAX_LIST_ENTRIES,
    MAX_NAME_LENGTH,
    MAX_UPC_LENGTH,
    PullSourceClient,
    PullSourceOutage,
    parse_pull_payload,
)
from http_support import PUBLIC_V4, StubResolver, make_settings

WEEK = "2026-W31"
SOURCE_HOST = "walksoftly.example"
SOURCE_URL = f"https://{SOURCE_HOST}/newcomics.php"

#: Shape of a real cover URL: path-style on the shared S3 endpoint, under the
#: allowlisted ``/comicgeeks/`` prefix, with a cache-buster query.
PRIMARY_COVER = "https://s3.amazonaws.com/comicgeeks/comics/covers/large-4242.jpg"
ALT_COVER = "https://s3.amazonaws.com/comicgeeks/comics/covers/large-4243.jpg"

#: The relative placeholder the source sends for a book with no cover art.
NO_COVER_PLACEHOLDER = "/assets/images/no-cover-lg.jpg"

DESCRIPTION = "A lamplighter walks the drowned district looking for her sister."

#: Content columns compared across two stores — the surrogate id and fetch
#: stamp legitimately differ (replace-on-refresh reinserts every row).
_CONTENT_COLUMNS = (
    "entry_key",
    "publisher",
    "series_name",
    "issue_number",
    "cv_series_id",
    "cv_issue_id",
    "release_date",
    "match_type",
    "matched_issue_id",
    "cover_url",
    "description",
    "upc",
    "creators",
    "characters",
)


def _snapshot(row) -> dict:
    return {name: getattr(row, name) for name in _CONTENT_COLUMNS}


def _payload_entry(*, cache_buster: str = "1780169968", **overrides) -> dict:
    """One live-shaped raw entry. ``printings`` / ``link`` are present in the
    real payload and deliberately never ingested."""
    entry = {
        "series": "Hollow Lantern",
        "issue": "#3",
        "publisher": "Paper Tiger Press",
        "shipdate": "2026-07-29",
        "comicid": 55501,
        "issueid": 900501,
        "covers": [
            {"url": f"{ALT_COVER}?{cache_buster}", "is_primary": False},
            {"url": f"{PRIMARY_COVER}?{cache_buster}", "is_primary": True},
        ],
        "description": DESCRIPTION,
        "creators": [
            {"creator_id": 11, "role": "Writer", "name": "R. Halloway"},
            {"creator_id": 12, "role": "Artist", "name": "N. Vasquez"},
        ],
        "characters": [
            {"character_id": 71, "name": "The Lamplighter"},
            {"character_id": 72, "name": "Mother Tide"},
        ],
        "upc": "76194137701100311",
        "printings": [{"id": 1, "name": "1st printing"}],
        "link": "/comic/4242/hollow-lantern-3",
    }
    entry.update(overrides)
    return entry


async def _fetch(tmp_path: Path, payload: list[dict]):
    """Fetch one week through the real client over a stubbed transport — the
    ingest path end to end, no real DNS or I/O."""
    return await _fetch_body(
        tmp_path, json.dumps(payload).encode()
    )


async def _fetch_body(tmp_path: Path, body: bytes):
    """Like :func:`_fetch`, but the transport serves an exact byte body — so a
    field carrying a lone surrogate (``\\uD800``, a valid JSON escape) reaches
    the parser as the source really sends it, rather than failing at response
    construction the way ``httpx``'s ``json=`` encoder would."""
    factory = HttpClientFactory(
        make_settings(tmp_path),
        resolver=StubResolver({SOURCE_HOST: [PUBLIC_V4]}),
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body)),
    )
    client = PullSourceClient(factory, SOURCE_URL)
    async with client:
        return await client.fetch_week(week=31, year=2026)


async def _store_and_read(db, entries) -> list:
    async with db.write_session() as session:
        await repo.replace_week(session, WEEK, entries)
    async with db.read_session() as session:
        return await repo.list_week(session, WEEK)


# --- idempotent storage of the canonical cover + text fields -----------------


@pytest.mark.req("FRG-PULL-011")
async def test_enrichment_stores_idempotently_with_a_query_stripped_cover(db, tmp_path):
    """Fetching and storing the same week twice — with a DIFFERENT cover
    cache-buster each time, exactly as the live source behaves — yields
    identical rows, because the stored cover URL drops the query."""
    snapshots = []
    for cache_buster in ("1780169968", "1780900123"):
        entries = await _fetch(tmp_path, [_payload_entry(cache_buster=cache_buster)])
        rows = await _store_and_read(db, entries)
        snapshots.append([_snapshot(row) for row in rows])

    assert snapshots[0] == snapshots[1]

    (stored,) = snapshots[0]
    assert stored["cover_url"] == PRIMARY_COVER  # primary chosen, query stripped
    assert stored["description"] == DESCRIPTION
    assert stored["upc"] == "76194137701100311"
    # Source-internal creator/character ids are dropped — nothing links to them.
    assert json.loads(stored["creators"]) == [
        {"role": "Writer", "name": "R. Halloway"},
        {"role": "Artist", "name": "N. Vasquez"},
    ]
    assert json.loads(stored["characters"]) == [
        {"name": "The Lamplighter"},
        {"name": "Mother Tide"},
    ]


@pytest.mark.req("FRG-PULL-011")
async def test_first_cover_is_used_when_none_is_flagged_primary(db, tmp_path):
    entries = await _fetch(
        tmp_path,
        [
            _payload_entry(
                covers=[
                    {"url": f"{ALT_COVER}?9", "is_primary": False},
                    {"url": f"{PRIMARY_COVER}?9", "is_primary": False},
                ]
            )
        ],
    )
    (row,) = await _store_and_read(db, entries)
    assert row.cover_url == ALT_COVER


@pytest.mark.req("FRG-PULL-011")
async def test_absent_enrichment_stores_as_null_not_empty_string(db, tmp_path):
    """A minimal entry (the six original keys only) still stores — every
    enrichment column is simply NULL."""
    entries = await _fetch(
        tmp_path,
        [{"series": "Paper Tigers", "issue": "1", "shipdate": "2026-07-29"}],
    )
    (row,) = await _store_and_read(db, entries)
    assert row.series_name == "Paper Tigers"
    assert row.cover_url is None
    assert row.description is None
    assert row.upc is None
    assert row.creators is None
    assert row.characters is None


# --- fail-closed cover validation -------------------------------------------


@pytest.mark.req("FRG-PULL-011")
@pytest.mark.parametrize(
    "hostile_url",
    [
        NO_COVER_PLACEHOLDER,  # relative placeholder — not a fetchable target
        "http://s3.amazonaws.com/comicgeeks/comics/covers/large-1.jpg",  # not https
        "https://evil.example/comicgeeks/comics/covers/large-1.jpg",  # off-host
        "https://s3.amazonaws.com/other-bucket/large-1.jpg",  # off-prefix
        "https://s3.amazonaws.com/comicgeeks-evil/large-1.jpg",  # prefix lookalike
        # Virtual-hosted form of the same bucket: the shared-endpoint rule is
        # exact-host precisely so a bucket subdomain cannot skip the prefix.
        "https://comicgeeks.s3.amazonaws.com/comics/covers/large-1.jpg",
        "https://s3.amazonaws.com/comicgeeks/../other-bucket/large-1.jpg",  # traversal
        "https://s3.amazonaws.com/comicgeeks/%2e%2e/other-bucket/x.jpg",  # encoded
        "https://u:p@s3.amazonaws.com/comicgeeks/large-1.jpg",  # userinfo
        "https://s3.amazonaws.com:8443/comicgeeks/large-1.jpg",  # non-default port
        "https://s3.amazonaws.com/comicgeeks/a\x01b.jpg",  # control char in path
    ],
)
async def test_hostile_or_placeholder_cover_stores_null_entry_otherwise_intact(
    db, tmp_path, hostile_url
):
    """Fail closed: the entry stores normally, the run succeeds, and the URL
    nothing may fetch never reaches the database."""
    entries = await _fetch(
        tmp_path,
        [_payload_entry(covers=[{"url": hostile_url, "is_primary": True}])],
    )
    (row,) = await _store_and_read(db, entries)

    assert row.cover_url is None
    # Everything else about the entry survived — a refused cover is cosmetic.
    assert row.series_name == "Hollow Lantern"
    assert row.issue_number == "#3"
    assert row.description == DESCRIPTION
    assert row.upc == "76194137701100311"
    assert json.loads(row.creators)[0]["name"] == "R. Halloway"


@pytest.mark.req("FRG-PULL-011")
def test_malformed_covers_container_is_not_fatal():
    """A ``covers`` value that is not a list of objects — or an object with no
    usable url — degrades to no cover, never to a dropped entry."""
    for covers in (None, "not-a-list", [], [None, 7], [{"is_primary": True}], [{"url": ""}]):
        (entry,) = parse_pull_payload(
            json.dumps([_payload_entry(covers=covers)]).encode()
        )
        assert entry.cover_url is None, covers
        assert entry.series_name == "Hollow Lantern"


# --- bounded text + count-capped lists --------------------------------------


@pytest.mark.req("FRG-PULL-011")
async def test_oversized_and_control_laden_enrichment_is_bounded_not_fatal(db, tmp_path):
    entries = await _fetch(
        tmp_path,
        [
            _payload_entry(
                description="D" * (MAX_DESCRIPTION_LENGTH + 500),
                upc="9" * (MAX_UPC_LENGTH + 40),
                creators=[
                    {"role": "R" * 200, "name": f"Creator {i:03d}"}
                    for i in range(MAX_LIST_ENTRIES + 20)
                ],
                characters=[
                    # RLO (U+202E) + ZWSP (U+200B) buried in the name, and an
                    # oversized second name.
                    {"name": "Mo‮ther​ Tide"},
                    {"name": "C" * (MAX_NAME_LENGTH + 100)},
                    {"name": "   "},  # nothing printable — dropped
                ],
            )
        ],
    )
    (row,) = await _store_and_read(db, entries)

    assert len(row.description) == MAX_DESCRIPTION_LENGTH
    assert len(row.upc) == MAX_UPC_LENGTH

    creators = json.loads(row.creators)
    assert len(creators) == MAX_LIST_ENTRIES  # count-capped
    assert creators[0]["name"] == "Creator 000"  # order preserved
    assert all(len(c["role"]) <= 64 for c in creators)

    characters = json.loads(row.characters)
    assert [c["name"] for c in characters] == [
        "Mother Tide",  # bidi/zero-width stripped
        "C" * MAX_NAME_LENGTH,  # truncated
    ]


@pytest.mark.req("FRG-PULL-011")
def test_creator_without_a_usable_name_is_dropped_role_may_be_absent():
    (entry,) = parse_pull_payload(
        json.dumps(
            [
                _payload_entry(
                    creators=[
                        {"role": "Writer"},  # no name — a credit attached to no one
                        {"name": "K. Adeyemi"},  # no role — kept, role null
                        "not-an-object",
                    ]
                )
            ]
        ).encode()
    )
    assert json.loads(entry.creators) == [{"role": None, "name": "K. Adeyemi"}]


# --- lone-surrogate robustness (write path must never abort the run) ---------


@pytest.mark.req("FRG-PULL-011")
async def test_lone_surrogate_in_text_fields_stores_successfully(db, tmp_path):
    """A lone UTF-16 surrogate (``\\uD800``) in a text field — which the DB
    driver cannot bind and which would otherwise roll back the whole multi-week
    write — is stripped at ingest so the row persists intact."""
    entries = await _fetch(
        tmp_path,
        [
            _payload_entry(
                description="Ink \ud800 blot",
                upc="12\ud80034",
                creators=[{"role": "Writer", "name": "R. \ud800 Halloway"}],
            )
        ],
    )
    (row,) = await _store_and_read(db, entries)  # must not raise UnicodeEncodeError

    assert row.series_name == "Hollow Lantern"  # the row actually persisted
    assert "\ud800" not in row.description
    assert row.description == "Ink blot"
    assert row.upc == "1234"
    assert "\ud800" not in row.creators
    assert json.loads(row.creators) == [{"role": "Writer", "name": "R. Halloway"}]


# --- primary/sibling cover selection ----------------------------------------


@pytest.mark.req("FRG-PULL-011")
async def test_off_allowlist_primary_does_not_suppress_a_valid_sibling(db, tmp_path):
    """A hostile URL flagged primary is skipped (it fails the allowlist), and
    the first VALID sibling is stored — a bad primary cannot deny a good cover."""
    entries = await _fetch(
        tmp_path,
        [
            _payload_entry(
                covers=[
                    {"url": "https://evil.example/x.jpg", "is_primary": True},
                    {"url": f"{PRIMARY_COVER}?9", "is_primary": False},
                ]
            )
        ],
    )
    (row,) = await _store_and_read(db, entries)
    assert row.cover_url == PRIMARY_COVER


@pytest.mark.req("FRG-PULL-011")
async def test_is_primary_must_be_exactly_true_not_merely_truthy(db, tmp_path):
    """``is_primary`` forces selection only when it is exactly ``True`` — a
    truthy ``1`` or the string ``"false"`` does not, so the first valid cover in
    order is used."""
    entries = await _fetch(
        tmp_path,
        [
            _payload_entry(
                covers=[
                    {"url": f"{ALT_COVER}?9", "is_primary": 1},
                    {"url": f"{PRIMARY_COVER}?9", "is_primary": "false"},
                ]
            )
        ],
    )
    (row,) = await _store_and_read(db, entries)
    assert row.cover_url == ALT_COVER  # first valid, since neither is exactly True


# --- non-string scalars store as absent, never a Python repr ----------------


@pytest.mark.req("FRG-PULL-011")
@pytest.mark.parametrize("junk", [{"nested": "obj"}, [1, 2, 3], True])
def test_non_string_scalar_enrichment_stores_absent(junk):
    """A non-string description / upc / name is dropped (``strings_only``),
    never coerced to ``str(...)`` and stored as a Python repr."""
    (entry,) = parse_pull_payload(
        json.dumps(
            [
                _payload_entry(
                    description=junk,
                    upc=junk,
                    creators=[{"role": "Writer", "name": junk}],
                    characters=[{"name": junk}],
                )
            ]
        ).encode()
    )
    assert entry.description is None
    assert entry.upc is None
    assert entry.creators is None  # the sole creator had no usable name
    assert entry.characters is None


# --- deeply-nested body degrades to an outage, never RecursionError ----------


@pytest.mark.req("FRG-PULL-011")
def test_deeply_nested_body_degrades_to_outage_not_recursionerror():
    """A hostile deeply-nested JSON body blows Python's recursion limit inside
    ``json.loads``; the parser catches it and degrades to a source outage
    (``reason='malformed'``) rather than letting a ``RecursionError`` escape and
    fail the run with the source still marked healthy."""
    body = b"[" * 100_000 + b"]" * 100_000
    with pytest.raises(PullSourceOutage) as excinfo:
        parse_pull_payload(body)
    assert excinfo.value.reason == "malformed"


# --- read-path robustness: a malformed stored blob decodes to [] -------------


@pytest.mark.req("FRG-PULL-011")
async def test_read_path_decodes_malformed_enrichment_blob_as_empty(db, tmp_path):
    """A row whose ``creators``/``characters`` column holds a hand-written
    malformed JSON blob (non-JSON, an object, a bare array, deeply nested) reads
    back through the API decode as an empty list — never a 500."""
    import datetime as dt

    from foragerr.pull.models import ParsedPullEntry

    blobs = (
        "not-json-at-all",
        "{}",
        "[1,2,3]",
        "[" * 5000 + "]" * 5000,  # deeply nested — decode must not recurse-crash
    )
    entries = [
        ParsedPullEntry(
            series_name=f"Corrupt Ledger {i}",
            issue_number=str(i),
            release_date=dt.date(2026, 7, 29),
            creators=blob,
            characters=blob,
        )
        for i, blob in enumerate(blobs)
    ]
    rows = await _store_and_read(db, entries)

    assert len(rows) == len(blobs)
    for row in rows:
        # The malformed blob round-tripped through storage unchanged...
        assert row.creators in blobs
        # ...and the read path degrades it to [] rather than raising.
        assert _creators(row.creators) == []
        assert _characters(row.characters) == []
        assert _decode_list(row.creators) == []
