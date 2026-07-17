"""The deployment-security posture record exists and stays in sync
(FRG-DEP-017): the committed posture document carries every decided
position, and the manual carries the operator-facing projection."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
POSTURE = REPO / "docs" / "security" / "posture.md"
MANUAL = REPO / "docs" / "manual" / "admin" / "security.md"


@pytest.mark.req("FRG-DEP-017")
def test_posture_document_covers_every_decided_position():
    text = POSTURE.read_text()
    # One anchor phrase per position the requirement enumerates — a section
    # can be reworded, but a position cannot silently disappear.
    for anchor in (
        "TLS is the deployment layer's job",
        "Full-database encryption is rejected",
        "Full-disk encryption is recommended",
        "FRG-NFR-014",  # DoS envelope cites the implementing requirement
        "RISK-005",  # archive-memory residual position
        "No CORS, by position",
        "trusted_proxies",
        "v0.9.0",  # downgrade warning names the floor version
        "no-new-privileges",
    ):
        assert anchor in text, f"posture.md lost its position anchor: {anchor!r}"


@pytest.mark.req("FRG-DEP-017")
def test_manual_carries_the_operator_projection():
    text = MANUAL.read_text()
    for anchor in (
        "FORAGERR_TRUSTED_PROXIES",
        "full-disk encryption",
        "no-new-privileges",
        "cap_drop",
        "v0.9.0",  # downgrade warning
        "tailscale serve",
    ):
        assert anchor.lower() in text.lower(), f"manual security.md lost: {anchor!r}"
    # The projection must point back at the position authority.
    assert "posture.md" in text
