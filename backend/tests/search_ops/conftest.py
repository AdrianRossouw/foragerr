"""Fixtures for the search-integration (area 3) tests.

Lives beside the tests (no package ``__init__``) so, like the other test
packages, it can pull the flat ``http_support`` / ``indexers_support`` helpers
off ``sys.path`` under pytest's prepend import mode.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import select

# The area-3 tests reuse the indexer test builders (``indexers_support``), which
# live in the sibling ``tests/indexers`` directory. Put it on sys.path so the
# import resolves whether this package is run alone or with the full suite.
_INDEXERS_DIR = Path(__file__).resolve().parent.parent / "indexers"
if str(_INDEXERS_DIR) not in sys.path:
    sys.path.insert(0, str(_INDEXERS_DIR))

from foragerr.indexers import ratelimit
from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow
from foragerr.library import repo


@pytest.fixture(autouse=True)
def _reset_indexer_gates():
    """Isolate the process-global per-indexer rate gates around every test."""
    ratelimit.reset_gates()
    yield
    ratelimit.reset_gates()


@pytest.fixture
async def format_profile_id(db) -> int:
    """The id of the seeded default format profile (FRG-QUAL-002)."""
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
