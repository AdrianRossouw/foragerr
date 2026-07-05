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


# A child that overrides the built-in ``noop`` handler to block FOREVER inside
# an offload — i.e. a handler stuck in a blocking thread past the drain grace.
_CHILD_BLOCKING_OFFLOAD = (
    "import threading\n"
    "from foragerr.commands.registry import register_handler\n"
    "_never = threading.Event()\n"
    "@register_handler('noop')\n"
    "async def _blocking_noop(command, ctx):\n"
    "    await ctx.offload(_never.wait)\n"
    "    return 'never'\n"
    "from foragerr.app import main\n"
    "main()\n"
)


def _spawn_blocking_offload_app(config_dir: Path, port: int, grace: str):
    config_dir.mkdir(exist_ok=True)
    backend_dir = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["FORAGERR_CONFIG_DIR"] = str(config_dir)
    env["FORAGERR_HOST"] = "127.0.0.1"
    env["FORAGERR_PORT"] = str(port)
    env["FORAGERR_SHUTDOWN_GRACE_SECONDS"] = grace
    return subprocess.Popen(
        [sys.executable, "-c", _CHILD_BLOCKING_OFFLOAD],
        cwd=str(backend_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def _enqueue_noop(port: int) -> int:
    response = httpx.post(
        f"http://127.0.0.1:{port}/api/v1/command", json={"name": "noop"}, timeout=5.0
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _wait_status(port: int, command_id: int, target: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = httpx.get(
            f"http://127.0.0.1:{port}/api/v1/command/{command_id}", timeout=2.0
        )
        if response.status_code == 200 and response.json()["status"] == target:
            return
        time.sleep(0.05)
    raise AssertionError(f"command {command_id} never reached {target!r}")


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


@pytest.mark.req("FRG-DEP-008")
def test_repeated_sigterm_escalates_to_force_exit():
    """A SECOND shutdown signal must force-exit. Uvicorn's own handle_exit only
    escalates on a repeated SIGINT; the docker/systemd pattern is a repeated
    SIGTERM, which by default does nothing once should_exit is set."""
    import uvicorn

    from foragerr.app import _ForagerrServer

    async def _app(scope, receive, send):  # minimal ASGI app; never invoked here
        raise AssertionError("not called")

    server = _ForagerrServer(uvicorn.Config(_app))
    assert not server.should_exit and not server.force_exit

    server.handle_exit(signal.SIGTERM, None)
    assert server.should_exit is True
    assert server.force_exit is False  # first signal: graceful drain

    server.handle_exit(signal.SIGTERM, None)
    assert server.force_exit is True  # second SIGTERM now forces exit


@pytest.mark.req("FRG-DEP-008")
@pytest.mark.req("FRG-SCHED-011")
def test_handler_blocked_in_offload_still_exits_within_the_grace_bound(tmp_path):
    """A handler wedged forever in a blocking offload must not stop the process
    from exiting within the drain bound: the offload runs on a DAEMON thread,
    so interpreter exit never join-blocks on it, and the abandoned command is
    named at CRITICAL for the operator."""
    config_dir = tmp_path / "cfg"
    port = _free_port()
    proc = _spawn_blocking_offload_app(config_dir, port, grace="3")
    try:
        _wait_for_health(port)
        command_id = _enqueue_noop(port)
        _wait_status(port, command_id, "started")

        start = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        try:
            returncode = proc.wait(timeout=25)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
            raise AssertionError("interpreter hung on a non-daemon offload thread")
        elapsed = time.monotonic() - start
        output = proc.stdout.read().decode("utf-8", "replace") if proc.stdout else ""

        assert elapsed < 15.0, output  # bounded despite the wedged handler
        assert returncode == 0, output
        assert "level=CRITICAL" in output, output  # abandoned handler is named
        assert "noop#" in output, output
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


@pytest.mark.req("FRG-DEP-008")
def test_second_sigterm_forces_prompt_exit_despite_a_long_grace(tmp_path):
    """With a long drain grace and a wedged handler, a single SIGTERM would wait
    out the whole grace; a second SIGTERM force-exits promptly (skipping the
    drain), so an operator is never stuck waiting."""
    config_dir = tmp_path / "cfg"
    port = _free_port()
    proc = _spawn_blocking_offload_app(config_dir, port, grace="25")
    try:
        _wait_for_health(port)
        command_id = _enqueue_noop(port)
        _wait_status(port, command_id, "started")

        start = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        # Burst the repeat signal into the brief window before the drain await
        # begins; force_exit is idempotent so extra signals are harmless.
        for _ in range(4):
            time.sleep(0.03)
            proc.send_signal(signal.SIGTERM)
        try:
            returncode = proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
            raise AssertionError("second SIGTERM did not force a prompt exit")
        elapsed = time.monotonic() - start
        output = proc.stdout.read().decode("utf-8", "replace") if proc.stdout else ""

        assert elapsed < 15.0, output  # nowhere near the 25s grace: drain skipped
        assert returncode == 0, output
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
