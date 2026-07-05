"""Static guards: the outbound choke point is the ONLY HTTP call site, and
backend/src is print-free so nothing bypasses log redaction
(FRG-NFR-006, FRG-NFR-008)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "backend" / "src"
HTTP_PACKAGE = SRC_DIR / "foragerr" / "http"


def _grep_src(pattern: re.Pattern[str], *, allow_dir: Path | None = None) -> list[str]:
    offenders: list[str] = []
    for path in sorted(SRC_DIR.rglob("*.py")):
        if allow_dir is not None and path.is_relative_to(allow_dir):
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    return offenders


@pytest.mark.req("FRG-NFR-006")
def test_no_http_client_call_sites_outside_the_factory_package():
    """All outbound traffic flows through foragerr.http: no other module may
    import (and therefore use) httpx or requests."""
    pattern = re.compile(r"^\s*(?:import|from)\s+(?:httpx|requests)\b")
    offenders = _grep_src(pattern, allow_dir=HTTP_PACKAGE)
    assert not offenders, (
        "outbound HTTP call sites outside foragerr/http/ "
        "(FRG-NFR-006 choke point violated):\n" + "\n".join(offenders)
    )
    # sanity: the guard itself sees the factory's legitimate import
    assert _grep_src(pattern), "guard pattern found no httpx import at all"


@pytest.mark.req("FRG-NFR-006")
@pytest.mark.req("FRG-NFR-008")
def test_no_print_calls_in_backend_src():
    """print() bypasses the redaction logging filter — banned in backend/src
    (design: m1-foundation risk note on filter-based redaction)."""
    pattern = re.compile(r"(?<![\w.])print\s*\(")
    offenders = _grep_src(pattern)
    assert not offenders, (
        "print( call sites in backend/src bypass log redaction:\n"
        + "\n".join(offenders)
    )
