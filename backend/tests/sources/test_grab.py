"""Entitlement download + import handoff (FRG-SRC-006): fresh-signed-URL fetch,
HTTPS + CDN egress confinement, md5 verify → import-pending handoff, and a
checksum-mismatch quarantine on the per-entitlement failed surface.
"""

from __future__ import annotations

import hashlib

import httpx
import pytest
from sqlalchemy import select

from foragerr.http import HttpClientFactory
from foragerr.sources import ratelimit, repo
from foragerr.sources.grab import run_grab, sources_staging_dir
from foragerr.sources.models import SourceEntitlementRow
from foragerr.sources.registry import TYPE_HUMBLE
from foragerr.sources.service import run_sync
from foragerr.sources.settings import HumbleSettings
from http_support import PUBLIC_V4, StubResolver, make_settings
from sources_support import fixture_bytes, json_response

GAMEKEY = "aBcD1234synthetic"
FILE_BYTES = b"SYNTHETIC-COMIC-ARCHIVE-PAYLOAD" * 512
FILE_MD5 = hashlib.md5(FILE_BYTES).hexdigest()  # noqa: S324 — test integrity check


@pytest.fixture(autouse=True)
def _reset_gates():
    ratelimit.reset_gates()
    yield
    ratelimit.reset_gates()


def _grab_factory(config_dir, handler) -> HttpClientFactory:
    """A factory resolving BOTH the Humble API host and the CDN host to a
    policy-acceptable public IP, over an injected mock transport."""
    settings = make_settings(config_dir)
    resolver = StubResolver(
        {
            "www.humblebundle.com": [PUBLIC_V4],
            "dl.humble.com": [PUBLIC_V4],
            "cdn.humble.com": [PUBLIC_V4],
        }
    )
    return HttpClientFactory(
        settings, resolver=resolver, transport=httpx.MockTransport(handler)
    )


def _order_body(machine_name: str, web_url: str) -> bytes:
    import json

    return json.dumps(
        {
            "gamekey": GAMEKEY,
            "subproducts": [
                {
                    "machine_name": machine_name,
                    "human_name": "Synthetic Hero #1",
                    "downloads": [
                        {
                            "platform": "ebook",
                            "download_struct": [
                                {
                                    "name": "CBZ",
                                    "md5": FILE_MD5,
                                    "file_size": len(FILE_BYTES),
                                    "url": {"web": web_url},
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ).encode()


def _handler(*, order_body: bytes, serve_file: bool = True, file_status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/api/v1/order/"):
            return json_response(200, order_body)
        if serve_file and path.endswith(".cbz"):
            return httpx.Response(file_status, content=FILE_BYTES)
        return json_response(404, b"{}")

    return handler


async def _matched_entitlement(db, config_dir, *, md5: str) -> SourceEntitlementRow:
    """Sync, then mark the single-issue comic matched with the given expected md5."""
    source = await repo.create_source(
        db,
        source_type=TYPE_HUMBLE,
        name="Humble Bundle",
        settings=HumbleSettings(session_cookie="SYNTH-COOKIE"),
        connection_state="connected",
    )
    from sources_support import make_factory, order_handler

    sync_factory = make_factory(
        config_dir,
        httpx.MockTransport(
            order_handler(
                list_body=b'[{"gamekey":"%s"}]' % GAMEKEY.encode(),
                order_bodies={GAMEKEY: fixture_bytes("order_comics.json")},
            )
        ),
    )
    await run_sync(db, sync_factory, source, min_interval=0.0)
    async with db.write_session() as session:
        row = (
            await session.execute(
                select(SourceEntitlementRow).where(
                    SourceEntitlementRow.machine_name == "synth_singleissue_01"
                )
            )
        ).scalar_one()
        row.review_status = "matched"
        row.matched_series_id = 4321
        row.md5 = md5
        row.download_state = "queued"
        eid = row.id
    return await repo.get_entitlement(db, eid)


@pytest.mark.req("FRG-SRC-006")
async def test_happy_path_verifies_and_hands_off_to_import(db, config_dir):
    ent = await _matched_entitlement(db, config_dir, md5=FILE_MD5)
    settings = make_settings(config_dir)
    handler = _handler(
        order_body=_order_body(
            "synth_singleissue_01", "https://dl.humble.com/synth_hero_01.cbz?t=x"
        )
    )
    summary = await run_grab(
        db, _grab_factory(config_dir, handler), settings, ent.id, min_interval=0.0
    )
    assert "handed off to import" in summary

    # The entitlement is NOT yet imported — it waits on the drain (FRG-SRC-006):
    # (see also test_cdn_host_variant_is_allowlisted below)
    # ownership is never claimed before the file lands in the library.
    after = await repo.get_entitlement(db, ent.id)
    assert after.download_state == "import_pending"
    assert after.download_error is None

    # Handed to the existing import pipeline as a normal completed download:
    # a tracked_downloads row sits in import_pending pointing at the staged file.
    from foragerr.downloads.models import TrackedDownloadRow

    async with db.read_session() as session:
        tracked = (
            await session.execute(
                select(TrackedDownloadRow).where(
                    TrackedDownloadRow.download_id == f"humble:{ent.id}"
                )
            )
        ).scalar_one()
    assert tracked.state == "import_pending"
    assert tracked.series_id == 4321
    assert tracked.output_path.endswith(".cbz")


@pytest.mark.req("FRG-SRC-006")
async def test_handoff_is_deduped_on_download_id(db, config_dir):
    """Two handoffs for the same entitlement create exactly one tracked_downloads
    row — the client_id-NULL uniqueness gap is closed by a download_id dedup
    (FRG-SRC-004/006)."""
    from foragerr.sources.grab import _handoff_to_import, sources_staging_dir

    ent = await _matched_entitlement(db, config_dir, md5=FILE_MD5)
    folder = sources_staging_dir(config_dir) / str(ent.id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "synthetic.cbz"
    path.write_bytes(b"x")

    await _handoff_to_import(db, ent, path)
    await _handoff_to_import(db, ent, path)
    from foragerr.downloads.models import TrackedDownloadRow

    async with db.read_session() as session:
        rows = (
            (
                await session.execute(
                    select(TrackedDownloadRow).where(
                        TrackedDownloadRow.download_id == f"humble:{ent.id}"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1


@pytest.mark.req("FRG-SRC-006")
async def test_null_size_grab_is_refused(db, config_dir):
    """A NULL file_size entitlement is refused rather than streamed uncapped
    (disk-fill DoS guard, FRG-NFR-006)."""
    ent = await _matched_entitlement(db, config_dir, md5=FILE_MD5)
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, ent.id)
        row.file_size = None
        row.download_state = "queued"
    settings = make_settings(config_dir)
    handler = _handler(
        order_body=_order_body(
            "synth_singleissue_01", "https://dl.humble.com/synth_hero_01.cbz?t=x"
        )
    )
    summary = await run_grab(
        db, _grab_factory(config_dir, handler), settings, ent.id, min_interval=0.0
    )
    assert "no size" in summary
    after = await repo.get_entitlement(db, ent.id)
    assert after.download_state == "failed"
    assert "file size" in after.download_error


@pytest.mark.req("FRG-SRC-003")
async def test_unparseable_download_url_fails_not_strands(db, config_dir):
    """A crafted, unparseable url.web at grab time lands the entitlement failed
    (not stuck in fetching) (FRG-SRC-003 / FRG-NFR-012)."""
    ent = await _matched_entitlement(db, config_dir, md5=FILE_MD5)
    settings = make_settings(config_dir)
    handler = _handler(
        order_body=_order_body("synth_singleissue_01", "http://["),
        serve_file=False,
    )
    summary = await run_grab(
        db, _grab_factory(config_dir, handler), settings, ent.id, min_interval=0.0
    )
    assert "unparseable" in summary or "failed" in summary
    after = await repo.get_entitlement(db, ent.id)
    assert after.download_state == "failed"


@pytest.mark.req("FRG-SRC-006")
async def test_checksum_mismatch_quarantines_and_fails(db, config_dir):
    # Expected md5 deliberately disagrees with the served bytes.
    ent = await _matched_entitlement(db, config_dir, md5="f" * 32)
    settings = make_settings(config_dir)
    handler = _handler(
        order_body=_order_body(
            "synth_singleissue_01", "https://dl.humble.com/synth_hero_01.cbz?t=x"
        )
    )
    summary = await run_grab(
        db, _grab_factory(config_dir, handler), settings, ent.id, min_interval=0.0
    )
    assert "md5 mismatch" in summary

    after = await repo.get_entitlement(db, ent.id)
    assert after.download_state == "failed"
    assert "md5 mismatch" in after.download_error

    # The bad file is quarantined (never imported) and no import row is created.
    quarantine = sources_staging_dir(config_dir) / "quarantine"
    assert (quarantine / f"{ent.id}.partial").exists()
    from foragerr.downloads.models import TrackedDownloadRow

    async with db.read_session() as session:
        rows = (
            await session.execute(select(TrackedDownloadRow))
        ).scalars().all()
    assert rows == []


@pytest.mark.req("FRG-AUTH-012")
async def test_grab_with_undecryptable_cookie_fails_not_stranded(db, config_dir):
    """A grab whose source cookie cannot be decrypted (key missing/changed) fails
    cleanly instead of stranding the entitlement in 'fetching' (FRG-AUTH-012)."""
    from cryptography.fernet import Fernet, MultiFernet

    from foragerr import keystore as keystore_mod

    ent = await _matched_entitlement(db, config_dir, md5=FILE_MD5)
    # Rotate to a wrong key so the stored cookie can no longer be decrypted.
    wrong = keystore_mod.derive_fernet_key("nope", b"0123456789abcdef")
    keystore_mod.install_keystore(
        keystore_mod.Keystore(MultiFernet([Fernet(wrong)]), available=False)
    )
    settings = make_settings(config_dir)
    handler = _handler(
        order_body=_order_body(
            "synth_singleissue_01", "https://dl.humble.com/synth_hero_01.cbz?t=x"
        )
    )
    summary = await run_grab(
        db, _grab_factory(config_dir, handler), settings, ent.id, min_interval=0.0
    )
    assert "credential unavailable" in summary
    after = await repo.get_entitlement(db, ent.id)
    assert after.download_state == "failed"
    assert "encryption key" in after.download_error


@pytest.mark.req("FRG-SRC-006")
async def test_cdn_host_variant_is_allowlisted(db, config_dir):
    """Live Humble serves signed URLs from cdn.humble.com as well as
    dl.humble.com (observed 2026-07-22 — the research doc had only seen
    dl.*); both apex domains are trusted so Humble-side CDN naming drift
    never refuses a real download. Regression for the live failure
    'download URL is outside the provider allowlist: cdn.humble.com'."""
    ent = await _matched_entitlement(db, config_dir, md5=FILE_MD5)
    settings = make_settings(config_dir)
    handler = _handler(
        order_body=_order_body(
            "synth_singleissue_01", "https://cdn.humble.com/synth_hero_01.cbz?t=x"
        )
    )
    summary = await run_grab(
        db, _grab_factory(config_dir, handler), settings, ent.id, min_interval=0.0
    )
    assert "handed off to import" in summary


@pytest.mark.req("FRG-SRC-006")
async def test_apex_suffix_match_has_a_dot_boundary(db, config_dir):
    """`humble.com` on the allowlist must NOT admit `evilhumble.com` — the
    subdomain rule matches on a dot boundary, never a bare suffix."""
    ent = await _matched_entitlement(db, config_dir, md5=FILE_MD5)
    settings = make_settings(config_dir)
    handler = _handler(
        order_body=_order_body(
            "synth_singleissue_01", "https://evilhumble.com/x.cbz"
        ),
        serve_file=False,
    )
    summary = await run_grab(
        db, _grab_factory(config_dir, handler), settings, ent.id, min_interval=0.0
    )
    assert "download failed" in summary
    after = await repo.get_entitlement(db, ent.id)
    assert after.download_state == "failed"


@pytest.mark.req("FRG-SRC-006")
async def test_egress_off_allowlist_is_refused(db, config_dir):
    ent = await _matched_entitlement(db, config_dir, md5=FILE_MD5)
    settings = make_settings(config_dir)
    # The order returns a download URL on a NON-Humble host.
    handler = _handler(
        order_body=_order_body(
            "synth_singleissue_01", "https://evil.example.com/x.cbz"
        ),
        serve_file=False,
    )
    summary = await run_grab(
        db, _grab_factory(config_dir, handler), settings, ent.id, min_interval=0.0
    )
    assert "download failed" in summary

    after = await repo.get_entitlement(db, ent.id)
    assert after.download_state == "failed"
    assert "allowlist" in after.download_error or "refused" in after.download_error
