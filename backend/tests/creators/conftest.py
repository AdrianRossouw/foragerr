"""Shared fixtures for the creators test package.

Mirrors the library package's flow fixtures (default format profile + a root
folder) so the reconciliation tests can drive a real ``refresh_series`` through
the same ``FakeCV`` harness the library tests use.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from foragerr.commands import CommandService
from foragerr.library import repo
from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow

from flows_support import flows_settings


@pytest.fixture(autouse=True)
def _reset_cv_gate():
    from foragerr.metadata import ratelimit

    ratelimit.reset_gate()
    yield
    ratelimit.reset_gate()


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return flows_settings(cfg)


@pytest.fixture
async def commands(db, settings, command_registry):
    return CommandService(db, settings)


@pytest.fixture
async def format_profile_id(db) -> int:
    from sqlalchemy import select

    async with db.read_session() as session:
        result = await session.execute(
            select(FormatProfileRow.id).where(
                FormatProfileRow.name == DEFAULT_PROFILE_NAME
            )
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
