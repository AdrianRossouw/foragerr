"""Shared fixtures: env/log isolation for the foundation test suite."""

from __future__ import annotations

import logging
import os
from pathlib import Path

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
