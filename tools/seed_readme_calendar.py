#!/usr/bin/env python3
"""Seed a README-capture instance's current pull week from its own library.

Supports the `calendar` shot of ``tools/refresh-readme-shots.sh``
(FRG-PROC-017). The Calendar renders the CURRENT release week, and its shelf
presentation — cover, publisher chip, principal creators, description teaser
(FRG-UI-042) — draws on enrichment that only stored ``pull_entries`` carry
(FRG-PULL-011); the projection's library-primary half (FRG-PULL-001) carries
none of it, and a public-domain demo library store-dated in the 1940s puts
nothing in the current week either. So a capture instance's Calendar is bare
unless the week is seeded.

The live weekly feed cannot be that seed: README shots are public and must
show public-domain content only, and no third party's uptime may decide
whether the tour can be refreshed (the same reason the capture instance pins
``pull_enabled`` off). This seeds the week from the instance's OWN imported
public-domain library instead — one entry per selected issue, linked to that
issue (``match_type`` "id") so each row's derived state, monitor toggle and
search action are the real thing rather than a mock, with the cover taken from
ComicVine (the only host family ``foragerr.covers`` admits, so a locally
served fixture image could never render) and the creator line taken from the
credits the import already ingested.

What is synthetic is the release DATE: golden-age issues are placed across the
current week so the shelf has days to group by. Everything else on the row —
title, issue number, publisher, cover, creators, description — is that issue's
real ComicVine metadata, already in the instance's database.

Refuses to run against a week that already holds stored entries, so it can
never overwrite a real pull refresh's work. Point it only at a throwaway
capture instance: it writes release dates a live refresh would then reconcile
against the real feed.

Run it with the environment the capture instance booted with: it resolves the
same settings the instance did, so it finds the same config dir, database and
ComicVine key without being told any of them twice. Prints the number of
entries written.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
from itertools import zip_longest

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from foragerr.config import load_settings
from foragerr.covers import canonical_cover_url
from foragerr.creators.models import CreatorRow, IssueCreditRow
from foragerr.db.engine import database_path
from foragerr.http import HttpClientFactory
from foragerr.library.models import IssueFileRow, IssueRow, SeriesRow
from foragerr.metadata.comicvine import ComicVineClient
from foragerr.pull.models import PullEntryRow
from foragerr.pull.projection import current_week, week_date_range

#: Entries taken from each series. Two keeps the shelf's visible rows on
#: distinct series (they are dealt round-robin across days below) while still
#: filling a plausible week from a four-series demo library.
ISSUES_PER_SERIES = 2

#: Days of the week entries are dealt across, starting at Monday. A real week
#: clusters on the mid-week ship day; three groups give the agenda enough day
#: headers to read as a week without spreading four series too thin.
RELEASE_DAY_OFFSETS = (1, 2, 3)

#: Credits carried onto an entry. The row prints at most two writers and two
#: artists (FRG-UI-042); the rest only reach the expanded detail surface.
MAX_CREDITS = 10

#: Description cap, mirroring the ingest's posture of storing a bounded
#: display string rather than whatever length the source hands over.
MAX_DESCRIPTION = 600


def _fail(message: str) -> None:
    print(f"seed_readme_calendar: {message}", file=sys.stderr)
    raise SystemExit(1)


def _credits_json(session: Session, issue_id: int) -> str | None:
    """The issue's ingested credits in the stored enrichment shape, or None
    when the issue has none (the row's creator line then collapses)."""
    rows = session.execute(
        select(IssueCreditRow.role_verbatim, CreatorRow.name)
        .join(CreatorRow, CreatorRow.id == IssueCreditRow.creator_id)
        .where(IssueCreditRow.issue_id == issue_id)
        .order_by(IssueCreditRow.id)
        .limit(MAX_CREDITS)
    ).all()
    if not rows:
        return None
    return json.dumps(
        [{"role": role, "name": name} for role, name in rows], separators=(",", ":")
    )


def _pick_issues(session: Session, series_id: int) -> list[IssueRow]:
    """Up to :data:`ISSUES_PER_SERIES` issues worth putting on the shelf.

    Prefers credited issues (an uncredited one renders without the creator
    line the shot is meant to show), and prefers one owned plus one missing so
    the captured week carries both derived states — a shelf where every row is
    already owned would not show the monitor/search affordances at all.
    """
    file_count = (
        select(func.count(IssueFileRow.id))
        .where(IssueFileRow.issue_id == IssueRow.id)
        .scalar_subquery()
    )
    credit_count = (
        select(func.count(IssueCreditRow.id))
        .where(IssueCreditRow.issue_id == IssueRow.id)
        .scalar_subquery()
    )
    rows = session.execute(
        select(IssueRow, file_count, credit_count)
        .where(IssueRow.series_id == series_id)
        .where(IssueRow.monitored.is_(True))
        .order_by(IssueRow.ordering_key)
    ).all()
    # Credited issues if the series has any; otherwise its issues regardless.
    # A row whose creator line collapses is still a truthful row, and dropping
    # a whole series would leave the shelf thinner than the week really is.
    credited = [(issue, files) for issue, files, credits in rows if credits]
    if not credited:
        credited = [(issue, files) for issue, files, _ in rows]
    owned = [issue for issue, files in credited if files]
    missing = [issue for issue, files in credited if not files]
    picked: list[IssueRow] = []
    # Interleave the two states, then top up from whichever is longer, so a
    # series that is fully owned (or fully missing) still contributes its share.
    for pool in (owned, missing):
        if pool:
            picked.append(pool[0])
    for pool in (owned, missing):
        for issue in pool:
            if len(picked) >= ISSUES_PER_SERIES:
                break
            if issue not in picked:
                picked.append(issue)
    return picked[:ISSUES_PER_SERIES]


async def _cover_urls(settings, volume_ids: list[int]) -> dict[int, str]:
    """ComicVine issue-cover URLs, keyed by ComicVine issue id.

    One paginated volume walk per series through the app's own client, so the
    fetch answers to the same rate limiter, budget and egress policy every
    other ComicVine call does. Every URL is put through the cover allowlist
    exactly as the real ingest does — a refused one is simply absent, and the
    row falls back to its publisher-tinted spine.
    """
    covers: dict[int, str] = {}
    factory = HttpClientFactory(settings)
    async with ComicVineClient(settings, factory) as cv:
        for volume_id in volume_ids:
            page = await cv.get_issues(volume_id)
            for record in page.items:
                if not record.image_url:
                    continue
                canonical = canonical_cover_url(record.image_url)
                if canonical:
                    covers[record.cv_issue_id] = canonical
    return covers


async def main() -> None:
    settings = load_settings()
    db_path = database_path(settings.config_dir)
    if not db_path.exists():
        _fail(f"no database under {settings.config_dir}")

    week = current_week()
    monday, _ = week_date_range(week)
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        existing = session.execute(
            select(func.count(PullEntryRow.id)).where(PullEntryRow.week == week)
        ).scalar_one()
        if existing:
            _fail(f"week {week} already holds {existing} stored entries — refusing")

        series = session.execute(
            select(SeriesRow).where(SeriesRow.monitored.is_(True)).order_by(SeriesRow.sort_title)
        ).scalars().all()
        if not series:
            _fail("no monitored series to seed the week from")

        # Deal round-robin so consecutive rows come from different series: the
        # shot's visible rows should read as a week's variety, not as one
        # series' run, and same-series rows share a description. zip_longest,
        # not slicing: a series that could only contribute one issue must not
        # shift every later series' turn.
        per_series = [
            [(s, issue) for issue in _pick_issues(session, s.id)] for s in series
        ]
        dealt = [
            pair
            for turn in zip_longest(*per_series)
            for pair in turn
            if pair is not None
        ]
        if not dealt:
            _fail("no credited issues found — the import's credits fetch produced none")

        covers = await _cover_urls(settings, [s.cv_volume_id for s in series])
        now = dt.datetime.now(dt.timezone.utc)
        for index, (series_row, issue) in enumerate(dealt):
            day = RELEASE_DAY_OFFSETS[index % len(RELEASE_DAY_OFFSETS)]
            description = series_row.description_sanitized
            session.add(
                PullEntryRow(
                    week=week,
                    entry_key=f"cv:{issue.cv_issue_id}",
                    publisher=series_row.publisher,
                    series_name=series_row.title,
                    issue_number=issue.issue_number or "1",
                    cv_series_id=series_row.cv_volume_id,
                    cv_issue_id=issue.cv_issue_id,
                    release_date=monday + dt.timedelta(days=day),
                    matched_issue_id=issue.id,
                    match_type="id",
                    fetched_at=now,
                    cover_url=covers.get(issue.cv_issue_id),
                    description=description[:MAX_DESCRIPTION] if description else None,
                    upc=None,
                    creators=_credits_json(session, issue.id),
                    characters=None,
                )
            )
        session.commit()
        print(f"seeded {len(dealt)} pull entries for {week}")


if __name__ == "__main__":
    asyncio.run(main())
