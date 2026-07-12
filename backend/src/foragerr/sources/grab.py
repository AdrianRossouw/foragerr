"""Entitlement download + import handoff (FRG-SRC-006, design decision 8).

An accepted (``matched``) comic entitlement is grabbed on the command backbone:

    queued → fetching → verifying → imported | failed

1. **Fresh signed URL** — re-fetched from the order API at grab time
   (:meth:`HumbleClient.fetch_download_url`); the signed URL is never stored.
2. **Egress confinement** — the URL must be HTTPS and on the Humble CDN host
   allowlist (:data:`HUMBLE_CDN_HOSTS`). Enforcement reuses the DDL area's
   :class:`~foragerr.ddl.download.AllowList` + per-redirect ``hop_check`` over
   the shared factory's ``external`` profile (the FRG-NFR-006 choke point):
   scheme+host are re-validated on every hop, on top of the always-on SSRF
   egress policy.
3. **Bounded stream** — :func:`~foragerr.ddl.download.download_link` streams to
   the staging area with the byte/size accounting + runaway cap it already
   enforces (FRG-NFR-006), seeded with the entitlement's API-declared size.
4. **md5 verify** — the streamed bytes are hashed and compared to the
   API-provided md5. A mismatch quarantines the file (never imported) and lands
   on the per-entitlement failed-download surface with retry (FRG-SRC-006).
5. **Import handoff** — a verified file is handed to the EXISTING import
   pipeline as a normal completed download: a ``grab_history`` row (series hint)
   + a ``tracked_downloads`` row in ``import_pending`` that
   ``ProcessImportsCommand`` drains through ``CompletedDownloadSource`` — the
   same seam SABnzbd/DDL completed downloads enter.

*Deviation (flagged):* a grab FAILURE surfaces on the entitlement's own
``download_state = "failed"`` + ``download_error`` axis (design decision 2), NOT
the usenet ``tracked_downloads`` failure loop — that loop writes a blocklist row
and auto-enqueues an indexer re-search, which is meaningless for an
account-owned store item (there is nothing to re-search). Retry re-queues the
grab, clearing the error.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, ClassVar, Literal
from urllib.parse import urlsplit

from foragerr.commands.registry import BaseCommand, register_command, register_handler
from foragerr.commands.service import HandlerContext
from foragerr.db.base import utcnow
from foragerr.ddl import download as dl
from foragerr.ddl.errors import DdlDownloadError
from foragerr.keystore import KeystoreDecryptError
from foragerr.security.paths import safe_path_component
from foragerr.sources import repo
from foragerr.sources.commands import make_humble_factory
from foragerr.sources.humble import HumbleAuthError, HumbleClient, HumbleError
from foragerr.sources.models import SourceEntitlementRow

logger = logging.getLogger("foragerr.sources.grab")

#: Command / task name for a single-entitlement grab.
SOURCE_GRAB_TASK = "source-grab"

#: The Humble CDN download hosts (research doc: dl.humble.com). HTTPS-only; the
#: AllowList matches an exact host or a subdomain of a listed host.
HUMBLE_CDN_HOSTS: frozenset[str] = frozenset({"dl.humble.com", "humblebundle.com"})

#: Streaming hash chunk (matches the DDL streaming chunk).
_HASH_CHUNK = 64 * 1024


def sources_staging_dir(config_dir) -> Path:
    """The store-source staging directory: ``<config>/sources-staging``."""
    return Path(config_dir) / "sources-staging"


def cdn_allowlist() -> dl.AllowList:
    """The HTTPS-only Humble CDN egress allowlist (FRG-SRC-006)."""
    return dl.AllowList(hosts=HUMBLE_CDN_HOSTS, scheme="https")


def _is_parseable_url(url: str) -> bool:
    """Whether ``url`` parses to an HTTPS URL with a host (defensive pre-check).

    A crafted ``url.web`` such as ``"http://["`` makes ``urlsplit`` raise
    ``ValueError`` deep in the download path; validating here turns that into a
    clean per-entitlement failure (FRG-SRC-003 / FRG-NFR-012)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return bool(parts.scheme) and bool(parts.hostname)


def compute_md5(path: Path) -> str:
    """The lowercase-hex md5 of a file (streamed; runs off-loop via ``offload``)."""
    digest = hashlib.md5()  # noqa: S324 — store-provided integrity check, not security
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


@register_command
class SourceGrabCommand(BaseCommand):
    """Download + import-handoff one accepted entitlement (FRG-SRC-006).

    On the ``download`` workload pool so store grabs are serialized with other
    downloads and polite to the store CDN."""

    name: Literal["source-grab"] = "source-grab"
    workload_class: ClassVar[str] = "download"
    entitlement_id: int


@register_handler("source-grab")
async def _handle_source_grab(command: SourceGrabCommand, ctx: HandlerContext) -> str:
    settings = ctx.settings
    if settings is None:  # pragma: no cover — always wired by CommandService
        raise RuntimeError("source-grab requires a settings-bearing service")
    factory = getattr(ctx, "http_factory", None) or make_humble_factory(settings)
    min_interval = float(settings.source_min_request_interval_seconds)
    return await run_grab(
        ctx.db,
        factory,
        settings,
        command.entitlement_id,
        min_interval=min_interval,
        offload=ctx.offload,
    )


async def run_grab(
    db,
    factory,
    settings,
    entitlement_id: int,
    *,
    min_interval: float,
    offload=None,
) -> str:
    """Fetch → verify → import one entitlement; return a one-line summary."""
    ent = await repo.get_entitlement(db, entitlement_id)
    if ent is None:
        return f"source-grab: entitlement {entitlement_id} gone; nothing to do"
    if ent.review_status != "matched":
        return f"source-grab: entitlement {entitlement_id} not accepted; skipped"
    if not (ent.md5 and ent.filename):
        await _fail(db, entitlement_id, "entitlement has no grabbable copy")
        return f"source-grab: entitlement {entitlement_id} not grabbable"
    if ent.file_size is None:
        # Without a declared size the streaming byte-ceiling would be unbounded
        # when the CDN also omits Content-Length (disk-fill DoS, FRG-NFR-006).
        # Refuse rather than stream uncapped.
        await _fail(db, entitlement_id, "entitlement has no declared file size to bound the download")
        return f"source-grab: entitlement {entitlement_id} not grabbable (no size)"

    source = await repo.get_source(db, ent.source_id)
    if source is None or source.connection_state != "connected":
        await _fail(db, entitlement_id, "source not connected")
        return f"source-grab: entitlement {entitlement_id} source not connected"

    try:
        settings_model = repo.load_source_settings(source.type, source.settings)
    except KeystoreDecryptError:
        # The stored cookie cannot be decrypted (encryption key missing/changed).
        # Fail this grab with a clear reason instead of leaving it stuck in
        # "fetching"; the health surface flags the credential-unavailable source
        # (FRG-AUTH-012).
        await _fail(
            db,
            entitlement_id,
            "credential unavailable — the encryption key is missing or changed; "
            "re-enter the store session cookie",
        )
        return f"source-grab: entitlement {entitlement_id} credential unavailable"
    cookie = settings_model.session_cookie.get_secret_value()

    await _set_state(db, entitlement_id, "fetching")

    staging = sources_staging_dir(settings.config_dir)
    partial = staging / f"{entitlement_id}.partial"
    allowlist = cdn_allowlist()
    try:
        async with HumbleClient(
            factory,
            cookie,
            source_id=source.id,
            min_interval=min_interval,
            base_url=settings.humble_base_url,
        ) as client:
            url = await client.fetch_download_url(
                ent.gamekey, ent.machine_name, md5=ent.md5
            )
            if not url:
                await _fail(db, entitlement_id, "order no longer offers this download")
                return f"source-grab: {entitlement_id} no download url"
            if not _is_parseable_url(url):
                # A crafted/garbled ``url.web`` that ``urlsplit`` cannot parse
                # would otherwise raise deep in the download path and strand the
                # entitlement in "fetching" (FRG-SRC-003 / FRG-NFR-012).
                await _fail(db, entitlement_id, "order returned an unparseable download URL")
                return f"source-grab: {entitlement_id} unparseable download url"
            outcome = await dl.download_link(
                factory=factory,
                url=url,
                partial_path=partial,
                allowlist=allowlist,
                search_expected=ent.file_size,
            )
    except HumbleAuthError:
        await _fail(db, entitlement_id, "Humble session expired during grab")
        return f"source-grab: {entitlement_id} session expired"
    except (DdlDownloadError, HumbleError, ValueError, OSError) as exc:
        # ValueError: an unparseable URL slipping through to urlsplit.
        # OSError: a write failure (e.g. disk full) mid-stream.
        partial.unlink(missing_ok=True)
        await _fail(db, entitlement_id, f"download refused/failed: {exc}")
        return f"source-grab: {entitlement_id} download failed"

    # md5 verify (off the event loop for a large archive).
    await _set_state(db, entitlement_id, "verifying")
    run = offload or _inline_offload
    actual = await run(compute_md5, outcome.partial_path)
    if actual != ent.md5:
        quarantined = _quarantine(staging, outcome.partial_path, entitlement_id)
        await _fail(
            db,
            entitlement_id,
            f"md5 mismatch: expected {ent.md5}, got {actual} "
            f"(quarantined at {quarantined.name})",
        )
        return f"source-grab: {entitlement_id} md5 mismatch (quarantined)"

    # Re-read guard before the irreversible import handoff (FRG-SRC-004): the
    # operator may have ignored/un-matched the entitlement while we were
    # downloading. Abort rather than fabricate a completed download for an item
    # no longer accepted — the ignore path has already cleared the download axis.
    fresh = await repo.get_entitlement(db, entitlement_id)
    if fresh is None or fresh.review_status != "matched":
        outcome.partial_path.unlink(missing_ok=True)
        logger.info(
            "source-grab: entitlement %s no longer matched mid-grab; aborting import",
            entitlement_id,
        )
        return f"source-grab: {entitlement_id} no longer matched; import aborted"

    final_path = _promote(staging, outcome.partial_path, ent, entitlement_id)
    await _handoff_to_import(db, ent, final_path)
    # The entitlement stays on the download axis as ``import_pending`` — it is
    # advanced to ``imported`` only when ProcessImportsCommand actually lands the
    # file in the library (FRG-SRC-006), so ownership is never claimed early.
    await _set_state(db, entitlement_id, "import_pending", clear_error=True)
    return f"source-grab: {entitlement_id} handed off to import ({final_path.name})"


# --- import handoff ---------------------------------------------------------


async def _handoff_to_import(
    db, ent: SourceEntitlementRow, final_path: Path
) -> None:
    """Enter the verified file into the existing import pipeline (FRG-SRC-006).

    Writes a ``grab_history`` row (the series hint the importer's
    ``CompletedDownloadSource`` reconciles by download id) and a
    ``tracked_downloads`` row in ``import_pending`` — exactly the state
    ``ProcessImportsCommand`` drains. ``client_id`` is ``None`` (no polled
    client): the row is never observed by the tracking reconcile (it is not
    ``downloading`` and its download id is unseen), so it is never regressed.
    """
    from sqlalchemy import select

    from foragerr.downloads.models import GrabHistoryRow, TrackedDownloadRow
    from foragerr.downloads.state import TRACKED_STATUS_OK, TrackedDownloadState

    download_id = f"humble:{ent.id}"
    now = utcnow()
    async with db.write_session() as session:
        # Idempotency guard (FRG-SRC-004): the tracked_downloads uniqueness
        # constraint is (client_id, download_id) and client_id is NULL here, so
        # SQLite would NOT reject a duplicate. Dedup explicitly on the humble:
        # download_id so a re-accept / re-run never spawns a second grab-import
        # row for the same entitlement.
        existing = (
            await session.execute(
                select(TrackedDownloadRow.id).where(
                    TrackedDownloadRow.download_id == download_id
                )
            )
        ).first()
        if existing is not None:
            return
        session.add(
            GrabHistoryRow(
                download_id=download_id,
                client_id=None,
                series_id=ent.matched_series_id,
                issue_id=None,
                title=ent.human_name,
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
                series_id=ent.matched_series_id,
                issue_id=None,
                title=ent.human_name,
                output_path=str(final_path),
                encrypted=False,
                added_at=now,
                updated_at=now,
            )
        )


# --- filesystem -------------------------------------------------------------


def _promote(staging: Path, partial: Path, ent: SourceEntitlementRow, eid: int) -> Path:
    """Move the verified partial into a per-grab folder under a safe name.

    The completed download is a folder containing the archive (mirroring a real
    client's completed dir), so the importer walks it via
    ``CompletedDownloadSource``. The name is built from the store title +
    verified extension via ``safe_path_component`` — never a remote value —
    preserving the ``#N`` issue token so the parser resolves the issue within the
    matched series."""
    folder = staging / str(eid)
    folder.mkdir(parents=True, exist_ok=True)
    base = safe_path_component(ent.human_name, fallback=f"humble-{eid}")
    ext = _extension_for(ent)
    final = folder / f"{base}{ext}"
    partial.replace(final)
    return final


def _extension_for(ent: SourceEntitlementRow) -> str:
    """The safe on-disk extension from the preferred format token."""
    fmt = (ent.preferred_format or "").lower()
    return f".{fmt}" if fmt and fmt.isalnum() and len(fmt) <= 4 else ".cbz"


def _quarantine(staging: Path, partial: Path, eid: int) -> Path:
    """Move a checksum-failed file aside so it is never imported (FRG-SRC-006)."""
    quarantine = staging / "quarantine"
    quarantine.mkdir(parents=True, exist_ok=True)
    dest = quarantine / f"{eid}.partial"
    try:
        partial.replace(dest)
    except OSError:
        partial.unlink(missing_ok=True)
    return dest


# --- entitlement state writes ----------------------------------------------


async def _set_state(
    db, entitlement_id: int, state: str, *, clear_error: bool = False
) -> None:
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, entitlement_id)
        if row is not None:
            row.download_state = state
            if clear_error:
                row.download_error = None
            row.updated_at = utcnow()


async def _fail(db, entitlement_id: int, reason: str) -> None:
    """Land the grab on the per-entitlement failed surface (FRG-SRC-006)."""
    logger.warning("source-grab: entitlement %s failed: %s", entitlement_id, reason)
    async with db.write_session() as session:
        row = await session.get(SourceEntitlementRow, entitlement_id)
        if row is not None:
            row.download_state = "failed"
            row.download_error = reason[:500]
            row.updated_at = utcnow()


async def _inline_offload(func, *args, **kwargs) -> Any:
    return func(*args, **kwargs)


__all__ = [
    "HUMBLE_CDN_HOSTS",
    "SOURCE_GRAB_TASK",
    "SourceGrabCommand",
    "cdn_allowlist",
    "compute_md5",
    "run_grab",
    "sources_staging_dir",
]
