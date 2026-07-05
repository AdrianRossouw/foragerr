"""The built-in DDL client's persistent, single-flight download queue engine.

The one place DDL state lives — the ``ddl_queue`` table — replacing Mylar's
state smeared across a global lock, an in-memory ``queue.Queue`` and the
``ddl_info`` table that must be hand-synced (mylar-ddl §3.2). Items:

- are processed strictly one at a time (FRG-DDL-007): the engine runs on the
  ``download`` workload pool (size 1) behind an exclusivity group, and never
  starts a second download concurrently;
- survive restart (FRG-DDL-007): SCHED orphan recovery re-queues the
  ``process-ddl-queue`` command, and :meth:`DdlQueueEngine.reconcile_orphans`
  resets any ``downloading`` row left by a dead process back to ``queued`` —
  resumable from its on-disk partial;
- fail over per host (FRG-DDL-005): a failed link type is recorded on the row
  and the same release is retried via the next untried host (the post page is
  RE-FETCHED live each attempt, FRG-DDL-003); host exhaustion marks the item
  ``failed`` so the standard failed pipeline (blocklist + re-search, driven by
  the tracking area off ``ClientItem.status == failed``) takes over.

The engine is the DDL client's internal machinery; items reach the user only
projected through :meth:`foragerr.ddl.client.DdlClient.get_items` into the common
tracked-download view — never a second user-facing queue.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select, update

from foragerr.db.base import utcnow
from foragerr.ddl import download as dl
from foragerr.ddl.adapter_v1 import parse_post_page, url_host
from foragerr.ddl.errors import AdapterDrift, DdlDownloadError
from foragerr.ddl.links import (
    DownloadStrategy,
    Host,
    LinkCandidate,
    classify_host,
    classify_quality,
    dispatch_for,
    is_paywall_host,
    order_candidates,
    parse_host_priority,
)
from foragerr.ddl.settings import DEFAULT_GETCOMICS_URL, GetComicsSettings
from foragerr.ddl.verify import verify_file
from foragerr.downloads.models import DdlQueueRow
from foragerr.http import HttpClientFactory, OutboundHttpError
from foragerr.indexers.models import IndexerRow

logger = logging.getLogger("foragerr.ddl.queue")

# ddl_queue.status values.
STATUS_QUEUED = "queued"
STATUS_DOWNLOADING = "downloading"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_PAUSED = "paused"
STATUS_ABORTED = "aborted"

#: Post-page byte cap (an article page is small; guards a runaway/lying host).
POST_PAGE_MAX_BYTES = 4_000_000


@dataclass(frozen=True, slots=True)
class EnqueueRequest:
    """The intent to download one GetComics post (from the DDL client)."""

    download_id: str
    post_url: str
    title: str
    series_id: int | None = None
    issue_id: int | None = None
    provider_id: int | None = None
    expected_size: int | None = None


class DdlQueueEngine:
    """Persistent single-flight processor over ``ddl_queue`` (FRG-DDL-007)."""

    def __init__(
        self,
        db,
        *,
        http_factory: HttpClientFactory,
        staging_dir: Path,
        host_priority: list[Host] | None = None,
        prefer_upscaled: bool = True,
    ) -> None:
        self._db = db
        self._factory = http_factory
        self._staging = Path(staging_dir)
        self._host_priority = host_priority or parse_host_priority(
            "main,mirror,pixeldrain,mediafire,mega"
        )
        self._prefer_upscaled = prefer_upscaled

    # -- enqueue -------------------------------------------------------------

    async def enqueue(self, request: EnqueueRequest) -> int:
        """Insert a queued ``ddl_queue`` row; return its id (idempotent on the
        unique ``download_id``)."""
        now = utcnow()
        async with self._db.write_session() as session:
            existing = (
                await session.execute(
                    select(DdlQueueRow).where(
                        DdlQueueRow.download_id == request.download_id
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing.id
            row = DdlQueueRow(
                download_id=request.download_id,
                status=STATUS_QUEUED,
                series_id=request.series_id,
                issue_id=request.issue_id,
                provider_id=request.provider_id,
                post_url=request.post_url,
                title=request.title,
                expected_size=request.expected_size,
                bytes_received=0,
                attempts=0,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.flush()
            return row.id

    # -- restart safety ------------------------------------------------------

    async def reconcile_orphans(self) -> int:
        """Reset any ``downloading`` row back to ``queued`` (FRG-DDL-007).

        Called at engine start: a row still ``downloading`` means the process
        died mid-download; it is resumable from its on-disk ``.partial``."""
        now = utcnow()
        async with self._db.write_session() as session:
            result = await session.execute(
                update(DdlQueueRow)
                .where(DdlQueueRow.status == STATUS_DOWNLOADING)
                .values(status=STATUS_QUEUED, updated_at=now)
            )
        count = result.rowcount or 0
        if count:
            logger.warning("ddl: re-queued %d orphaned in-flight item(s)", count)
        return count

    # -- processing ----------------------------------------------------------

    async def process_all(self, *, limit: int = 100) -> int:
        """Process queued items one at a time until none remain (single-flight)."""
        processed = 0
        while processed < limit:
            if not await self.process_next():
                break
            processed += 1
        return processed

    async def process_next(self) -> bool:
        """Claim and fully process the oldest queued item; ``False`` if none."""
        row_id = await self._claim_next()
        if row_id is None:
            return False
        await self._process_item(row_id)
        return True

    async def _claim_next(self) -> int | None:
        now = utcnow()
        async with self._db.write_session() as session:
            row = (
                await session.execute(
                    select(DdlQueueRow)
                    .where(DdlQueueRow.status == STATUS_QUEUED)
                    .order_by(DdlQueueRow.id.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            row.status = STATUS_DOWNLOADING
            row.updated_at = now
            return row.id

    async def _process_item(self, row_id: int) -> None:
        """Run per-host failover for one item until success or exhaustion."""
        snapshot = await self._load(row_id)
        if snapshot is None:
            return
        provider_base = await self._provider_base_url(snapshot.provider_id)
        allowlist = dl.build_allowlist(provider_base)
        failed: set[str] = set(_json_list(snapshot.failed_hosts_json))

        # Bound the loop by the number of distinct hosts (failed set grows).
        for _ in range(len(Host) + 1):
            try:
                candidates = await self._resolve_candidates(
                    snapshot.post_url, provider_base, failed
                )
            except AdapterDrift as drift:
                await self._mark_failed(row_id, f"post-page drift: {drift.reason}")
                return
            except DdlDownloadError as exc:
                await self._mark_failed(row_id, f"post page unavailable: {exc}")
                return
            if not candidates:
                await self._mark_failed(
                    row_id, "all hosts exhausted" if failed else "no usable links"
                )
                return
            picked = candidates[0]
            await self._set_current(row_id, picked)
            try:
                verified_path, received = await self._attempt(
                    row_id, snapshot, picked, allowlist
                )
            except DdlDownloadError as exc:
                failed.add(picked.link_type)
                await self._record_host_failure(row_id, sorted(failed), str(exc))
                continue
            await self._complete(row_id, snapshot, picked, verified_path, received)
            return
        await self._mark_failed(row_id, "all hosts exhausted")

    async def _attempt(
        self,
        row_id: int,
        snapshot: DdlQueueRow,
        picked: LinkCandidate,
        allowlist: dl.AllowList,
    ) -> tuple[Path, int]:
        """One host attempt: download → verify. Raises DdlDownloadError to fail
        over. Mega/MediaFire/Pixeldrain are enumerated but unsupported in M1 —
        their concrete handler fails cleanly so failover advances (FRG-DDL-005),
        never the silent no-op of Mylar's dispatch typo (§3.3)."""
        if picked.strategy is DownloadStrategy.UNSUPPORTED:
            raise DdlDownloadError(
                f"host {picked.host} ({picked.link_type}) is not supported in M1; "
                "failing over"
            )
        partial = dl.partial_path_for(self._staging, row_id)
        outcome = await dl.download_link(
            factory=self._factory,
            url=picked.url,
            partial_path=partial,
            allowlist=allowlist,
            search_expected=snapshot.expected_size,
        )
        verified = verify_file(outcome.partial_path)
        name = dl.safe_output_name(
            series_title=await self._series_title(snapshot.series_id),
            issue_number=await self._issue_number(snapshot.issue_id),
            issue_id=snapshot.issue_id,
            queue_id=row_id,
            ext=verified.ext,
            fallback_title=snapshot.title,
        )
        final_path = dl.resolve_output_path(self._staging, name)
        outcome.partial_path.replace(final_path)
        return final_path, outcome.bytes_received

    async def _resolve_candidates(
        self, post_url: str, provider_base: str, failed: set[str]
    ) -> list[LinkCandidate]:
        """Fetch the post page LIVE, enumerate links, drop failed/paywall, order
        (FRG-DDL-003/004). Paywall/shortener links are rejected at parse and
        never fetched."""
        html = await self._fetch_post_page(post_url)
        candidates: list[LinkCandidate] = []
        for raw in parse_post_page(html, base_url=provider_base):
            host = classify_host(raw.host_label)
            if host is None:
                continue  # read-online / non-download anchor
            if is_paywall_host(url_host(raw.url)):
                continue  # paywall/shortener rejected at parse (FRG-DDL-004)
            handler = dispatch_for(host)
            if handler.link_type in failed:
                continue
            candidates.append(
                LinkCandidate(
                    host=host,
                    quality=classify_quality(raw.quality_label),
                    link_type=handler.link_type,
                    url=raw.url,
                    strategy=handler.strategy,
                )
            )
        return order_candidates(
            candidates,
            host_priority=self._host_priority,
            prefer_upscaled=self._prefer_upscaled,
        )

    async def _fetch_post_page(self, post_url: str) -> str:
        client = self._factory.external()
        try:
            result = await client.get(post_url, max_bytes=POST_PAGE_MAX_BYTES)
        except OutboundHttpError as exc:
            raise DdlDownloadError(f"post page fetch refused: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise DdlDownloadError("post page fetch failed") from exc
        finally:
            await client.aclose()
        if result.status_code != 200:
            raise DdlDownloadError(f"post page HTTP {result.status_code}")
        return result.content.decode("utf-8", errors="replace")

    # -- manual queue actions (FRG-DDL-007) ----------------------------------

    async def retry(self, download_id: str) -> bool:
        """Re-queue a failed/aborted item for a fresh attempt (clears failures)."""
        return await self._transition(
            download_id,
            STATUS_QUEUED,
            reset_failures=True,
            from_states=(STATUS_FAILED, STATUS_ABORTED, STATUS_PAUSED),
        )

    async def resume(self, download_id: str) -> bool:
        """Re-queue a paused item, keeping its partial + failed-host history."""
        return await self._transition(
            download_id,
            STATUS_QUEUED,
            reset_failures=False,
            from_states=(STATUS_PAUSED, STATUS_FAILED),
        )

    async def abort(self, download_id: str) -> bool:
        """Stop an item; it stays visible as aborted until removed."""
        return await self._transition(
            download_id,
            STATUS_ABORTED,
            reset_failures=False,
            from_states=(STATUS_QUEUED, STATUS_DOWNLOADING, STATUS_PAUSED),
        )

    async def remove(self, download_id: str, *, delete_data: bool = False) -> bool:
        """Delete an item's row and (optionally) its staged/partial files."""
        async with self._db.write_session() as session:
            row = (
                await session.execute(
                    select(DdlQueueRow).where(
                        DdlQueueRow.download_id == download_id
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return False
            row_id, output_path = row.id, row.output_path
            await session.delete(row)
        if delete_data:
            self._delete_files(row_id, output_path)
        return True

    async def _transition(
        self,
        download_id: str,
        to_state: str,
        *,
        reset_failures: bool,
        from_states: tuple[str, ...],
    ) -> bool:
        now = utcnow()
        async with self._db.write_session() as session:
            row = (
                await session.execute(
                    select(DdlQueueRow).where(
                        DdlQueueRow.download_id == download_id
                    )
                )
            ).scalar_one_or_none()
            if row is None or row.status not in from_states:
                return False
            row.status = to_state
            if reset_failures:
                row.failed_hosts_json = None
                row.last_error = None
            row.updated_at = now
            return True

    # -- transitions ---------------------------------------------------------

    async def _set_current(self, row_id: int, picked: LinkCandidate) -> None:
        async with self._db.write_session() as session:
            row = await session.get(DdlQueueRow, row_id)
            if row is not None:
                row.current_host = str(picked.host)
                row.current_link = picked.url
                row.selected_link_type = picked.link_type
                row.attempts = (row.attempts or 0) + 1
                row.updated_at = utcnow()

    async def _record_host_failure(
        self, row_id: int, failed: list[str], error: str
    ) -> None:
        # Discard this host's partial: the next host starts clean, so a failed
        # host's bytes can never be resumed onto a different host's stream
        # (cross-host corruption). Restart-resume (FRG-DDL-009) keeps its partial
        # because orphan recovery records no host failure.
        dl.partial_path_for(self._staging, row_id).unlink(missing_ok=True)
        async with self._db.write_session() as session:
            row = await session.get(DdlQueueRow, row_id)
            if row is not None:
                row.failed_hosts_json = json.dumps(failed)
                row.last_error = error
                row.updated_at = utcnow()

    async def _complete(
        self,
        row_id: int,
        snapshot: DdlQueueRow,
        picked: LinkCandidate,
        final_path: Path,
        received: int,
    ) -> None:
        """Mark verified-complete with provenance (FRG-DDL-013).

        Provenance (provider, post URL, selected host/link type, queue id) is
        persisted on the row; the DDL client's ``get_items()`` projects the
        completed item into the common tracked view where the tracking area
        transitions it to ``import_pending`` and records history."""
        async with self._db.write_session() as session:
            row = await session.get(DdlQueueRow, row_id)
            if row is not None:
                row.status = STATUS_COMPLETED
                row.output_path = str(final_path)
                row.bytes_received = received
                row.current_host = str(picked.host)
                row.selected_link_type = picked.link_type
                row.last_error = None
                row.updated_at = utcnow()
        logger.info(
            "ddl: item completed",
            extra={
                "download_id": snapshot.download_id,
                "host": str(picked.host),
                "link_type": picked.link_type,
                "issue_id": snapshot.issue_id,
            },
        )

    async def _mark_failed(self, row_id: int, reason: str) -> None:
        async with self._db.write_session() as session:
            row = await session.get(DdlQueueRow, row_id)
            if row is not None:
                row.status = STATUS_FAILED
                row.last_error = reason
                row.updated_at = utcnow()

    # -- lookups -------------------------------------------------------------

    async def _load(self, row_id: int) -> DdlQueueRow | None:
        async with self._db.read_session() as session:
            row = await session.get(DdlQueueRow, row_id)
            if row is not None:
                session.expunge(row)
            return row

    async def _provider_base_url(self, provider_id: int | None) -> str:
        if provider_id is None:
            return DEFAULT_GETCOMICS_URL
        async with self._db.read_session() as session:
            row = await session.get(IndexerRow, provider_id)
        if row is None:
            return DEFAULT_GETCOMICS_URL
        try:
            return GetComicsSettings.model_validate(json.loads(row.settings)).base_url
        except Exception:  # noqa: BLE001 — a corrupt provider row falls back
            return DEFAULT_GETCOMICS_URL

    async def _series_title(self, series_id: int | None) -> str | None:
        if series_id is None:
            return None
        from foragerr.library.models import SeriesRow

        async with self._db.read_session() as session:
            row = await session.get(SeriesRow, series_id)
            return row.title if row is not None else None

    async def _issue_number(self, issue_id: int | None) -> str | None:
        if issue_id is None:
            return None
        from foragerr.library.models import IssueRow

        async with self._db.read_session() as session:
            row = await session.get(IssueRow, issue_id)
            return row.issue_number if row is not None else None

    def _delete_files(self, row_id: int, output_path: str | None) -> None:
        for path in (dl.partial_path_for(self._staging, row_id), output_path):
            if path is None:
                continue
            try:
                Path(path).unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("ddl: could not delete %s: %s", path, exc)


def _json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except ValueError:
        return []
    return [str(v) for v in value] if isinstance(value, list) else []


__all__ = [
    "STATUS_ABORTED",
    "STATUS_COMPLETED",
    "STATUS_DOWNLOADING",
    "STATUS_FAILED",
    "STATUS_PAUSED",
    "STATUS_QUEUED",
    "DdlQueueEngine",
    "EnqueueRequest",
]
