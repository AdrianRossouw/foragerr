"""Shared fixtures + helpers for the importer (change-6) test package."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import select

from foragerr.importer.context import ImportContext
from foragerr.library import repo
from foragerr.library.paths import series_folder_name
from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow


@pytest.fixture
async def format_profile_id(db) -> int:
    async with db.read_session() as session:
        return (
            await session.execute(
                select(FormatProfileRow.id).where(
                    FormatProfileRow.name == DEFAULT_PROFILE_NAME
                )
            )
        ).scalar_one()


@pytest.fixture
async def library_root(db, tmp_path: Path) -> Path:
    root = tmp_path / "library"
    root.mkdir()
    async with db.write_session() as session:
        await repo.create_root_folder(session, str(root))
    return root


@dataclass
class SeededSeries:
    series_id: int
    issue_id: int
    cv_issue_id: int
    series_path: Path
    issue_number: str


@pytest.fixture
async def seed(db, library_root: Path, format_profile_id: int):
    """Factory: create a monitored series + one issue with an on-disk folder."""

    async def _make(
        *,
        title: str = "Batman",
        start_year: int | None = 1987,
        issue_number: str = "404",
        cv_volume_id: int = 42,
        cv_issue_id: int = 9001,
        issue_type: str = "regular",
    ) -> SeededSeries:
        folder = library_root / series_folder_name(title, start_year)
        folder.mkdir(parents=True, exist_ok=True)
        async with db.write_session() as session:
            series = await repo.create_series(
                session,
                cv_volume_id=cv_volume_id,
                title=title,
                start_year=start_year,
                format_profile_id=format_profile_id,
                root_folder_id=1,
                path=str(folder),
            )
            issue = await repo.create_issue(
                session,
                series_id=series.id,
                cv_issue_id=cv_issue_id,
                issue_number=issue_number,
                issue_type=issue_type,
            )
            return SeededSeries(
                series_id=series.id,
                issue_id=issue.id,
                cv_issue_id=cv_issue_id,
                series_path=folder,
                issue_number=issue_number,
            )

    return _make


@pytest.fixture
def import_ctx(library_root: Path, tmp_path: Path):
    """Factory for an :class:`ImportContext` with test-friendly defaults."""

    def _make(**overrides) -> ImportContext:
        config_dir = tmp_path / "config"
        config_dir.mkdir(exist_ok=True)
        defaults = dict(
            library_root=str(library_root),
            config_dir=str(config_dir),
            reference_year=2026,
            free_space_margin_bytes=0,
            junk_size_floor_bytes=64,
            now=dt.datetime(2026, 7, 5, 12, 0, 0),
        )
        defaults.update(overrides)
        return ImportContext(**defaults)

    return _make
