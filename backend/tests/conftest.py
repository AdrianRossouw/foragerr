"""Shared fixtures: env/log isolation for the foundation test suite."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Literal, Optional

import pytest

from foragerr import logging as flog


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Strip FORAGERR_* env vars and reset redaction/handler state per test."""
    for key in list(os.environ):
        if key.startswith("FORAGERR_"):
            monkeypatch.delenv(key)
    flog.clear_secrets()
    yield
    flog.clear_secrets()
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_foragerr", False):
            root.removeHandler(handler)
            handler.close()


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch) -> Path:
    """A fresh config directory, exported as FORAGERR_CONFIG_DIR."""
    path = tmp_path / "cfg"
    path.mkdir()
    monkeypatch.setenv("FORAGERR_CONFIG_DIR", str(path))
    return path


# --- db / sched area fixtures -------------------------------------------------


async def eventually(predicate, *, timeout: float = 5.0, interval: float = 0.02):
    """Poll ``predicate`` (sync or async) until truthy; fail after timeout."""
    deadline = time.monotonic() + timeout
    while True:
        result = predicate()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return result
        if time.monotonic() > deadline:
            raise AssertionError(f"condition not met within {timeout}s: {predicate}")
        await asyncio.sleep(interval)


@pytest.fixture
def migrated_dir(tmp_path: Path) -> Path:
    """A config dir whose database has been migrated to head."""
    from foragerr.db import prepare_database

    path = tmp_path / "dbcfg"
    path.mkdir()
    prepare_database(path)
    return path


@pytest.fixture
async def db(migrated_dir: Path):
    """A live Database over a head-revision schema."""
    from foragerr.db import Database

    database = Database(db_path=migrated_dir / "foragerr.db")
    yield database
    await database.close()


@pytest.fixture
def command_registry():
    """Snapshot/restore the command + handler registries around a test."""
    from foragerr.commands.registry import restore_registry, snapshot_registry

    snapshot = snapshot_registry()
    yield
    restore_registry(snapshot)


def define_command(
    name: str,
    *,
    workload_class: str = "default",
    exclusivity_group: str | None = None,
    default_priority: int = 0,
):
    """Register a throwaway command type with a single ``token`` payload field."""
    from foragerr.commands.registry import BaseCommand, register_command

    cls = type(
        f"TestCmd_{name}",
        (BaseCommand,),
        {
            "__annotations__": {"name": Literal[name], "token": Optional[str]},
            "name": name,
            "token": None,
            "workload_class": workload_class,
            "exclusivity_group": exclusivity_group,
            "default_priority": default_priority,
            "__module__": __name__,
        },
    )
    return register_command(cls)


@pytest.fixture
async def service(db, command_registry):
    """A running CommandService with default pool sizes and a fast poll."""
    from foragerr.commands import CommandService

    svc = CommandService(db, poll_interval=0.05)
    await svc.start()
    yield svc
    await svc.drain(1.0)
