"""Startup + pre-backup SQLite integrity checks (FRG-DB-012)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from foragerr.config import Settings
from foragerr.db import DB_FILENAME, prepare_database
from foragerr.db.backup_command import quick_check_startup_hook
from foragerr.db.integrity import run_full_integrity_check, run_quick_check
from foragerr.health.state import current_integrity, reset_integrity


@pytest.fixture(autouse=True)
def _reset_state():
    reset_integrity()
    yield
    reset_integrity()


def _clean_db(tmp_path: Path) -> Path:
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    prepare_database(cfg)
    return cfg / DB_FILENAME


@pytest.mark.req("FRG-DB-012")
def test_quick_and_full_check_pass_on_a_clean_db(tmp_path):
    db_path = _clean_db(tmp_path)
    quick = run_quick_check(db_path)
    full = run_full_integrity_check(db_path)
    assert quick.ok and quick.check == "quick_check"
    assert full.ok and full.check == "integrity_check"


@pytest.mark.req("FRG-DB-012")
def test_checks_fail_on_a_corrupt_db(tmp_path):
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"SQLite format 3\x00" + b"\xff" * 4096)
    quick = run_quick_check(corrupt)
    full = run_full_integrity_check(corrupt)
    assert not quick.ok and quick.errors
    assert not full.ok and full.errors


@pytest.mark.req("FRG-DB-012")
def test_missing_file_is_a_non_ok_result(tmp_path):
    result = run_quick_check(tmp_path / "does-not-exist.db")
    assert not result.ok
    assert "does not exist" in result.detail


@pytest.mark.req("FRG-DB-012")
async def test_startup_quick_check_marks_database_error_on_corruption(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / DB_FILENAME).write_bytes(b"SQLite format 3\x00" + b"\xff" * 4096)
    app = SimpleNamespace(state=SimpleNamespace(settings=Settings(config_dir=cfg)))

    await quick_check_startup_hook(app)  # app still "boots" — no raise

    state = current_integrity()
    assert state is not None and not state.ok
    assert state.source == "startup"
    assert state.detail  # names the integrity failure


@pytest.mark.req("FRG-DB-012")
async def test_startup_quick_check_reports_ok_for_a_clean_db(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    prepare_database(cfg)
    app = SimpleNamespace(state=SimpleNamespace(settings=Settings(config_dir=cfg)))

    await quick_check_startup_hook(app)

    state = current_integrity()
    assert state is not None and state.ok and state.source == "startup"
