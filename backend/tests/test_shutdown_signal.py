"""Full-process SIGTERM: clean, bounded exit and a WAL-checkpointed database
(FRG-DEP-008 — the process half; FRG-SCHED-011 owns the queue-drain half and
is tested there, not re-tagged here)."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_health(port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.0)
            if response.status_code in (200, 503):
                return
        except Exception as exc:  # connection refused while the server boots
            last_exc = exc
        time.sleep(0.1)
    raise AssertionError(f"server never became reachable on port {port}: {last_exc}")


@pytest.mark.req("FRG-DEP-008")
def test_sigterm_produces_a_clean_bounded_exit_and_checkpoints_the_wal(tmp_path):
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    port = _free_port()
    backend_dir = Path(__file__).resolve().parents[1]

    env = dict(os.environ)
    env["FORAGERR_CONFIG_DIR"] = str(config_dir)
    env["FORAGERR_HOST"] = "127.0.0.1"
    env["FORAGERR_PORT"] = str(port)
    env["FORAGERR_SHUTDOWN_GRACE_SECONDS"] = "5"

    proc = subprocess.Popen(
        [sys.executable, "-c", "from foragerr.app import main; main()"],
        cwd=str(backend_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_health(port)

        start = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        try:
            returncode = proc.wait(timeout=25)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
            raise AssertionError("process did not exit within the grace bound")
        elapsed = time.monotonic() - start

        assert elapsed < 29.0  # bounded grace period (FRG-DEP-008: < 30s)
        assert returncode == 0, (proc.stdout.read().decode("utf-8", "replace") if proc.stdout else "")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)

    wal_path = config_dir / "foragerr.db-wal"
    if wal_path.exists():
        assert wal_path.stat().st_size == 0, "WAL was not checkpointed at shutdown"

    # Restart against the same config dir: no recovery warnings, database
    # opens cleanly (FRG-DEP-008 scenario 3).
    import asyncio

    from foragerr.db import Database, prepare_database

    result = prepare_database(config_dir)
    assert result.applied == []  # already at head; no re-migration needed
    db = Database(db_path=config_dir / "foragerr.db")
    try:
        health = asyncio.run(db.health())
        assert health["status"] == "up"
    finally:
        asyncio.run(db.close())
