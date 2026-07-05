"""FRG-IMP-002 — pure, deterministic parse function."""

import os
import pathlib
import subprocess
import sys

import pytest

from foragerr import parser as parser_module
from foragerr.parser import parse

SRC = pathlib.Path(parser_module.__file__).parent

_SNIPPET = (
    "from foragerr.parser import parse;"
    "print(parse('Spider-Man 2099 001 (1992).cbz', reference_year=2026).to_json())"
)


@pytest.mark.req("FRG-IMP-002")
def test_identical_inputs_yield_byte_identical_results():
    results = {
        parse("Spider-Man 2099 001 (1992).cbz", reference_year=2026).to_json()
        for _ in range(25)
    }
    # shuffle call order relative to other parses
    parse("Batman 404 (1987).cbz", reference_year=2026)
    results.add(parse("Spider-Man 2099 001 (1992).cbz", reference_year=2026).to_json())
    assert len(results) == 1
    r = parse("Spider-Man 2099 001 (1992).cbz", reference_year=2026)
    assert r.series_name == "Spider-Man 2099"
    assert r.issue.value == 1 and r.issue.display == "001"
    assert r.year == 1992


@pytest.mark.req("FRG-IMP-002")
def test_byte_identical_across_processes_and_hash_seeds():
    outputs = set()
    for seed in ("0", "1", "random"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        out = subprocess.run(
            [sys.executable, "-c", _SNIPPET],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        ).stdout
        outputs.add(out)
    outputs.add(parse("Spider-Man 2099 001 (1992).cbz", reference_year=2026).to_json() + "\n")
    assert len(outputs) == 1


@pytest.mark.req("FRG-IMP-002")
@pytest.mark.req("FRG-IMP-013")
def test_future_year_governed_solely_by_reference_year():
    r2026 = parse("Spider-Man 2099 001 (1992).cbz", reference_year=2026)
    r2100 = parse("Spider-Man 2099 001 (1992).cbz", reference_year=2100)
    # 2099 is implausibly future at ref 2026 and remains title content;
    # the cover year is 1992 in both cases (rightmost plausible date).
    assert r2026.series_name == "Spider-Man 2099"
    assert r2026.year == 1992 and r2100.year == 1992
    assert r2026.issue.value == 1 and r2100.issue.value == 1


@pytest.mark.req("FRG-IMP-002")
def test_no_clock_config_watchlist_or_db_imports():
    forbidden = (
        "import datetime",
        "from datetime",
        "import time",
        "from time",
        "import os",
        "from os",
        "import socket",
        "import sqlite3",
        "import random",
        "from random",
        "import pathlib",
        "import urllib",
        "import requests",
        "import config",
        "from config",
    )
    for source in SRC.rglob("*.py"):
        text = source.read_text()
        for pattern in forbidden:
            assert pattern not in text, f"{source.name} contains {pattern!r}"


@pytest.mark.req("FRG-IMP-002")
def test_global_state_changes_cannot_alter_parse_output(monkeypatch, tmp_path):
    before = parse("Batman Annual 02 (2017).cbz", reference_year=2026)
    monkeypatch.setenv("FORAGERR_ANNUALS_ON", "0")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.ini").write_text("[parser]\nannuals_on = false\n")
    after = parse("Batman Annual 02 (2017).cbz", reference_year=2026)
    assert before.to_json() == after.to_json()
    assert after.issue.classification.value == "annual"
    assert after.issue.value == 2
