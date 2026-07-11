"""The external-bibliography fetch command (FRG-CRTR-005).

``creator-bibliography-fetch`` fetches a creator's broader ComicVine
bibliography — the volumes they are credited on that are NOT already in the
library — and caches a bounded, newest-first slice in ``creator_bibliography``,
replace-per-creator. It rides the command backbone exactly like ``refresh-series``:

* **Dedup is per creator** via the payload hash (FRG-SCHED-003): the payload is
  ``{creator_id}``, so two enqueues for the same creator collapse to one queued
  command — the same mechanism ``refresh-series`` relies on (no exclusivity group
  needed; distinct creators run independently).
* **ComicVine I/O happens OUTSIDE the write lock.** The handler reads the
  creator's ``cv_person_id`` and the library's series volume ids, then (outside
  any session) probes the person detail for volume stubs, excludes in-library
  volumes, hydrates a bounded working set, sorts newest-``start_year``-first, and
  caps the result. Only then does one write transaction replace the creator's
  cached rows and stamp ``bibliography_fetched_at``.
* **Failure preserves the cache.** Any typed ComicVine failure mid-run is logged
  and the command returns a failure summary WITHOUT raising and WITHOUT touching
  the cache or the stamp, so the previous suggestions survive and the unset/aged
  stamp drives a later retry.
* **It acquires nothing.** The handler writes ONLY ``creator_bibliography`` rows
  and the stamp — never a series, issue, search, download, or follow.

Stubs carry no ``start_year`` (the person endpoint serves id+name only), so
"newest-first" is applied over the HYDRATED candidate set: the not-in-library
stubs are hydrated (up to :data:`BIBLIOGRAPHY_WORKING_SET` of them, i.e. a few
batched requests), the full rows are sorted by ``start_year`` DESC (nulls last),
and the top :data:`BIBLIOGRAPHY_CAP` are cached. The working-set bound keeps even
a prolific creator to a small, constant number of CV requests (design decision 3).
"""

from __future__ import annotations

import logging
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.commands.registry import BaseCommand, register_command, register_handler
from foragerr.commands.service import HandlerContext
from foragerr.config import Settings
from foragerr.creators.models import CreatorBibliographyRow, CreatorRow
from foragerr.db import Database
from foragerr.db.base import utcnow
from foragerr.http import HttpClientFactory
from foragerr.library.flows._common import comicvine_factory
from foragerr.library.models import SeriesRow
from foragerr.metadata import ComicVineClient, ComicVineError, SeriesRecord

logger = logging.getLogger("foragerr.creators.bibliography")

#: Command name (1:1 with its handler).
BIBLIOGRAPHY_FETCH_COMMAND = "creator-bibliography-fetch"

#: How many cached suggestions to keep per creator, newest ``start_year`` first
#: (design decision 3). A constant with a comment; a config knob waits for demand.
BIBLIOGRAPHY_CAP = 24

#: Upper bound on the not-in-library stubs hydrated into the candidate set before
#: the sort+cap. Stubs carry no year, so "newest-first" must be decided over
#: HYDRATED rows — this bounds that hydration to a few batched requests
#: (``ceil(300 / VOLUMES_FILTER_CHUNK)`` = 3 chunks) even for a prolific creator,
#: at the cost of not seeing past the 300 most-recently-listed candidate volumes.
BIBLIOGRAPHY_WORKING_SET = 300


@register_command
class CreatorBibliographyFetchCommand(BaseCommand):
    """Fetch + cache one creator's external ComicVine bibliography (FRG-CRTR-005).

    Payload is the local ``creator_id``; dedup on the payload hash collapses
    repeat enqueues for the same creator to one queued command (FRG-SCHED-003),
    mirroring ``refresh-series``' per-series dedup."""

    name: Literal["creator-bibliography-fetch"] = "creator-bibliography-fetch"
    creator_id: int


async def _read_fetch_inputs(
    db: Database, creator_id: int
) -> tuple[int, set[int]] | None:
    """Read the creator's ``cv_person_id`` + the library's series volume ids.

    Returns ``None`` when the creator no longer exists (an unknown/deleted id is a
    recorded no-op, not a failure to raise on). Read up front so the ComicVine
    probes stay strictly OUTSIDE the write lock.
    """
    async with db.read_session() as session:
        cv_person_id = await session.scalar(
            select(CreatorRow.cv_person_id).where(CreatorRow.id == creator_id)
        )
        if cv_person_id is None:
            return None
        in_library = set(
            (await session.execute(select(SeriesRow.cv_volume_id))).scalars().all()
        )
    return int(cv_person_id), in_library


async def fetch_creator_bibliography(
    db: Database,
    settings: Settings,
    creator_id: int,
    *,
    factory: HttpClientFactory | None = None,
) -> str:
    """Fetch + cache one creator's external bibliography (FRG-CRTR-005).

    Returns a short human-readable summary that becomes the command's ``result``
    in job history. Never raises on a ComicVine failure — it logs and returns a
    failure summary, leaving the cache + stamp untouched for a later retry.
    """
    inputs = await _read_fetch_inputs(db, creator_id)
    if inputs is None:
        summary = f"creator {creator_id} no longer exists; bibliography fetch skipped"
        logger.info(summary)
        return summary
    cv_person_id, in_library = inputs

    # --- ComicVine I/O: strictly OUTSIDE the write lock -------------------------
    factory = factory or comicvine_factory(settings)
    try:
        async with ComicVineClient(settings, factory) as cv:
            stubs = await cv.get_person_volumes(cv_person_id)
            # Exclude in-library volumes at fetch time (the read side re-applies a
            # live anti-join, so a volume added later still disappears without a
            # refetch). Bound the working set BEFORE hydration — stubs carry no
            # year, so newest-first is decided over the hydrated rows below.
            candidate_ids = [
                stub.cv_volume_id
                for stub in stubs
                if stub.cv_volume_id not in in_library
            ][:BIBLIOGRAPHY_WORKING_SET]
            hydrated = (
                await cv.get_volumes_by_ids(candidate_ids) if candidate_ids else ()
            )
    except ComicVineError as exc:
        summary = (
            f"creator {creator_id} bibliography fetch failed, cache preserved: {exc}"
        )
        logger.warning(summary)
        return summary

    rows = _rank_and_cap(hydrated, in_library)

    # --- one write transaction: replace this creator's rows + stamp ------------
    async with db.write_session() as session:
        creator = await session.get(CreatorRow, creator_id)
        if creator is None:  # deleted between the read and the write
            summary = (
                f"creator {creator_id} removed mid-fetch; bibliography cache untouched"
            )
            logger.info(summary)
            return summary
        await _replace_bibliography(session, creator_id, rows)
        creator.bibliography_fetched_at = utcnow()

    summary = (
        f"creator {creator_id} bibliography: cached {len(rows)} volume(s) "
        f"(newest-first, capped at {BIBLIOGRAPHY_CAP})"
    )
    logger.info(summary)
    return summary


def _rank_and_cap(
    hydrated: tuple[SeriesRecord, ...], in_library: set[int]
) -> list[SeriesRecord]:
    """Sort the hydrated candidates newest-``start_year``-first and cap them.

    A missing ``start_year`` sorts last (``NULLS LAST``) via a two-key sort — a
    presence flag first, then the year — with ``cv_volume_id`` DESC as a stable
    tie-break. In-library volumes are dropped defensively (a hydration row could
    have been added to the library since the pre-I/O read); the read side does the
    authoritative live anti-join regardless.
    """
    candidates = [rec for rec in hydrated if rec.cv_volume_id not in in_library]
    candidates.sort(
        key=lambda rec: (
            rec.start_year is not None,
            rec.start_year or 0,
            rec.cv_volume_id,
        ),
        reverse=True,
    )
    return candidates[:BIBLIOGRAPHY_CAP]


async def _replace_bibliography(
    session: AsyncSession, creator_id: int, rows: list[SeriesRecord]
) -> None:
    """Replace a creator's cached bibliography rows atomically in this session.

    A volume whose name sanitized to ``None`` cannot satisfy the ``NOT NULL``
    ``title`` column, so it is dropped (a nameless volume is not a presentable
    suggestion). Everything else was already sanitized at the CV mapping boundary
    (FRG-META-014).
    """
    await session.execute(
        delete(CreatorBibliographyRow).where(
            CreatorBibliographyRow.creator_id == creator_id
        )
    )
    for rec in rows:
        if rec.name is None:
            continue
        session.add(
            CreatorBibliographyRow(
                creator_id=creator_id,
                cv_volume_id=rec.cv_volume_id,
                title=rec.name,
                publisher=rec.publisher,
                start_year=rec.start_year,
                count_of_issues=rec.count_of_issues,
            )
        )
    await session.flush()


@register_handler("creator-bibliography-fetch")
async def _handle_bibliography_fetch(
    command: CreatorBibliographyFetchCommand, ctx: HandlerContext
) -> str:
    if ctx.settings is None:  # pragma: no cover - always wired by CommandService
        raise RuntimeError(
            "creator-bibliography-fetch handler needs settings for the CV client"
        )
    return await fetch_creator_bibliography(ctx.db, ctx.settings, command.creator_id)


__all__ = [
    "BIBLIOGRAPHY_CAP",
    "BIBLIOGRAPHY_FETCH_COMMAND",
    "BIBLIOGRAPHY_WORKING_SET",
    "CreatorBibliographyFetchCommand",
    "fetch_creator_bibliography",
]
