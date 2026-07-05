"""Shared fixtures for the library test package."""

from __future__ import annotations

from pathlib import Path

import pytest

from foragerr.library import repo
from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow


@pytest.fixture
async def format_profile_id(db) -> int:
    """The id of the seeded default format profile (FRG-QUAL-002)."""
    from sqlalchemy import select

    async with db.read_session() as session:
        result = await session.execute(
            select(FormatProfileRow.id).where(FormatProfileRow.name == DEFAULT_PROFILE_NAME)
        )
        return result.scalar_one()


@pytest.fixture
async def root_folder_id(db, tmp_path: Path) -> int:
    root = tmp_path / "library-root"
    root.mkdir()
    async with db.write_session() as session:
        row = await repo.create_root_folder(session, str(root))
        return row.id


@pytest.fixture
def root_folder_path(tmp_path: Path) -> Path:
    return tmp_path / "library-root"
