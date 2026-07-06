"""Structured logging and secret redaction (FRG-DEP-006, FRG-NFR-008)."""

from __future__ import annotations

import logging
import shlex
from pathlib import Path

import pytest

from foragerr.logging import (
    LOG_FILENAME,
    MASK,
    register_secret,
    setup_logging,
)

SENTINEL = "sekrit-cv-key-1234567890"


def parse_kv_line(line: str) -> dict[str, str]:
    """Parse one structured key=value log line (proves parseability)."""
    fields = {}
    for token in shlex.split(line):
        key, sep, value = token.partition("=")
        assert sep, f"token {token!r} is not key=value"
        fields[key] = value
    return fields


def log_file(config_dir: Path) -> Path:
    return config_dir / "logs" / LOG_FILENAME


@pytest.mark.req("FRG-DEP-006")
def test_stdout_lines_are_parseable_structured_records(config_dir, capsys):
    setup_logging(config_dir, level="INFO")
    logging.getLogger("foragerr.test").info(
        "request handled ok", extra={"series": "X Men", "issues": 5}
    )
    line = capsys.readouterr().out.strip().splitlines()[-1]
    fields = parse_kv_line(line)
    assert fields["level"] == "INFO"
    assert fields["logger"] == "foragerr.test"
    assert fields["msg"] == "request handled ok"
    assert "T" in fields["ts"]  # ISO-8601 timestamp
    # caller-supplied extra fields ride along as key=value
    assert fields["series"] == "X Men"
    assert fields["issues"] == "5"


@pytest.mark.req("FRG-DEP-006")
def test_log_file_rotates_at_size_limit_and_respects_backup_count(config_dir):
    max_bytes, backups = 600, 2
    setup_logging(config_dir, level="INFO", max_bytes=max_bytes, backup_count=backups)
    log = logging.getLogger("foragerr.test.rotate")
    for i in range(80):
        log.info("rotation filler line %03d %s", i, "x" * 60)

    logs = sorted(p.name for p in (config_dir / "logs").iterdir())
    assert LOG_FILENAME in logs
    assert f"{LOG_FILENAME}.1" in logs  # rotation happened
    rotated = [name for name in logs if name.startswith(f"{LOG_FILENAME}.")]
    assert len(rotated) <= backups  # retention honoured
    for name in logs:
        # each file stays within the limit (plus one-record slack)
        assert (config_dir / "logs" / name).stat().st_size <= max_bytes + 200


@pytest.mark.req("FRG-DEP-006")
def test_log_level_parameter_controls_verbosity(config_dir, capsys):
    setup_logging(config_dir, level="INFO")
    logging.getLogger("foragerr.test").debug("debug-marker-quiet")
    assert "debug-marker-quiet" not in capsys.readouterr().out

    setup_logging(config_dir, level="DEBUG")
    logging.getLogger("foragerr.test").debug("debug-marker-loud")
    assert "debug-marker-loud" in capsys.readouterr().out


@pytest.mark.req("FRG-NFR-008")
def test_registered_secret_masked_in_message_args_and_traceback(config_dir, capsys):
    register_secret(SENTINEL)
    setup_logging(config_dir, level="INFO")
    log = logging.getLogger("foragerr.test.redact")

    log.error("inline secret: " + SENTINEL)  # (a) inline in the message
    log.error("arg secret: %s", SENTINEL)  # (b) via %s args
    try:  # (c) inside a formatted exception traceback
        raise ValueError(f"https://comicvine.example/api?x={SENTINEL} rejected")
    except ValueError:
        log.exception("upstream call failed")

    stdout = capsys.readouterr().out
    file_text = log_file(config_dir).read_text(encoding="utf-8")
    for output in (stdout, file_text):  # BOTH handlers must be covered
        assert SENTINEL not in output
        assert output.count(MASK) >= 3
    assert "ValueError" in file_text  # traceback still present, just masked


@pytest.mark.req("FRG-NFR-008")
def test_api_key_shaped_url_params_masked_without_registration(config_dir, capsys):
    setup_logging(config_dir, level="INFO")
    log = logging.getLogger("foragerr.test.urls")
    log.info(
        "GET https://indexer.example/api?apikey=zz9top&t=search&q=batman "
        "and https://cv.example/x?api_key=abc123&format=json"
    )
    stdout = capsys.readouterr().out
    file_text = log_file(config_dir).read_text(encoding="utf-8")
    for output in (stdout, file_text):
        assert "zz9top" not in output
        assert "abc123" not in output
        assert f"apikey={MASK}" in output
        assert f"api_key={MASK}" in output
        # non-secret query params stay readable
        assert "q=batman" in output
        assert "format=json" in output
