"""An expired store source surfaces as a health warning (FRG-SRC-005)."""

from __future__ import annotations

from pathlib import Path

import pytest

from foragerr.health.service import HealthService
from foragerr.sources.models import SourceRow
from foragerr.sources.registry import TYPE_HUMBLE
from foragerr.sources.repo import create_source, set_connection_state
from foragerr.sources.settings import HumbleSettings
from http_support import make_settings


async def _source(db, state: str) -> SourceRow:
    row = await create_source(
        db,
        source_type=TYPE_HUMBLE,
        name="Humble Bundle",
        settings=HumbleSettings(session_cookie="c"),
    )
    return await set_connection_state(db, row.id, state)


async def _warnings(db, tmp_path: Path):
    service = HealthService(db, make_settings(tmp_path))
    return await service.warnings()


@pytest.mark.req("FRG-SRC-005")
async def test_expired_source_is_a_health_warning(db, tmp_path):
    await _source(db, "expired")
    warnings = await _warnings(db, tmp_path)
    source_warnings = [w for w in warnings if w.source.startswith("source:")]
    assert len(source_warnings) == 1
    assert "expired" in source_warnings[0].message
    assert "reconnect" in source_warnings[0].message.lower()
    assert "cookie" in (source_warnings[0].remediation_hint or "").lower()


@pytest.mark.req("FRG-SRC-005")
async def test_connected_source_is_not_a_warning(db, tmp_path):
    await _source(db, "connected")
    warnings = await _warnings(db, tmp_path)
    assert not [w for w in warnings if w.source.startswith("source:")]


@pytest.mark.req("FRG-SRC-001")
async def test_disconnected_source_is_not_a_warning(db, tmp_path):
    await _source(db, "disconnected")
    warnings = await _warnings(db, tmp_path)
    assert not [w for w in warnings if w.source.startswith("source:")]
