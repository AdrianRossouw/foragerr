"""Shared helpers for the OPDS test suite (FRG-OPDS-001..006).

Seeds real library rows (root folder, series, issues, issue-files) plus the
matching archive files on disk, so the download route's containment check and
byte-identical streaming run against genuine paths — no path is ever fabricated
by a test the way a hostile client would try to.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from sqlalchemy import select

from foragerr.library import repo
from foragerr.library.paths import series_folder_name
from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow

from http_support import make_settings


def opds_settings(config_dir: Path, **overrides: Any):
    """Settings rooted in ``config_dir`` (OPDS needs no ComicVine/network)."""
    return make_settings(config_dir, **overrides)


async def _default_profile_id(session) -> int:
    return (
        await session.execute(
            select(FormatProfileRow.id).where(
                FormatProfileRow.name == DEFAULT_PROFILE_NAME
            )
        )
    ).scalar_one()


async def seed(app, root_path: Path, spec: list[dict]) -> dict:
    """Build a library under ``root_path`` from ``spec`` and return the created
    ids/paths/bytes for assertions.

    ``spec`` is a list of series dicts::

        {"title", "cv_volume_id", "start_year"?, "publisher"?,
         "issues": [{"cv_issue_id", "number"?, "title"?, "cover_date"?,
                     "store_date"?,
                     "files": [{"name", "data"(bytes)}]}]}
    """
    root_path = Path(root_path)
    root_path.mkdir(parents=True, exist_ok=True)
    db = app.state.db
    out: dict = {"root_path": str(root_path), "series": []}
    async with db.write_session() as session:
        profile_id = await _default_profile_id(session)
        root = await repo.create_root_folder(session, str(root_path))
        out["root_id"] = root.id
        for s in spec:
            start_year = s.get("start_year", 2012)
            series_dir = root_path / series_folder_name(s["title"], start_year)
            series_dir.mkdir(parents=True, exist_ok=True)
            series_row = await repo.create_series(
                session,
                cv_volume_id=s["cv_volume_id"],
                title=s["title"],
                publisher=s.get("publisher"),
                start_year=start_year,
                format_profile_id=profile_id,
                root_folder_id=root.id,
                path=str(series_dir),
            )
            sinfo: dict = {"id": series_row.id, "title": s["title"], "issues": []}
            for i in s.get("issues", []):
                issue_row = await repo.create_issue(
                    session,
                    series_id=series_row.id,
                    cv_issue_id=i["cv_issue_id"],
                    issue_number=i.get("number"),
                    title=i.get("title"),
                    cover_date=i.get("cover_date"),
                    store_date=i.get("store_date"),
                )
                iinfo: dict = {"id": issue_row.id, "files": []}
                for f in i.get("files", []):
                    fpath = series_dir / f["name"]
                    fpath.write_bytes(f["data"])
                    frow = await repo.add_issue_file(
                        session,
                        issue_id=issue_row.id,
                        path=str(fpath),
                        size=len(f["data"]),
                    )
                    iinfo["files"].append(
                        {
                            "id": frow.id,
                            "path": str(fpath),
                            "name": f["name"],
                            "data": f["data"],
                        }
                    )
                sinfo["issues"].append(iinfo)
            out["series"].append(sinfo)
    return out


def simple_series(
    title: str = "Saga",
    cv_volume_id: int = 1,
    *,
    n_issues: int = 3,
    ext: str = ".cbz",
    publisher: str | None = "Image",
) -> dict:
    """A one-series spec with ``n_issues`` issues, each with one archive file
    of unique bytes."""
    issues = []
    for n in range(1, n_issues + 1):
        issues.append(
            {
                "cv_issue_id": cv_volume_id * 1000 + n,
                "number": str(n),
                "title": f"{title} #{n}",
                "cover_date": dt.date(2012, 1, 1),
                "files": [
                    {
                        "name": f"{title} {n:03d}{ext}",
                        "data": f"{title}-issue-{n}-bytes".encode() * 4,
                    }
                ],
            }
        )
    return {
        "title": title,
        "cv_volume_id": cv_volume_id,
        "publisher": publisher,
        "issues": issues,
    }
