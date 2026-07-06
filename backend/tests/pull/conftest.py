"""Shared fixtures for the pull test package."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import seed_series_issue


@pytest.fixture
async def seed_series_issue_ids(db, tmp_path: Path) -> tuple[int, int]:
    """One monitored series ("Spawn") with one monitored issue (#1) — reused
    from the shared top-level helper so pull tests exercising
    `matched_issue_id` don't duplicate the library-domain seed."""
    return await seed_series_issue(db, tmp_path)
