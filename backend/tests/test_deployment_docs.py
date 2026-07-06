"""Labelling-control checks for the Tailscale-only exposure posture (FRG-DEP-011).

foragerr ships with no authentication in M1 (FRG-AUTH-001, accepted RISK-020);
the ONLY compensating control is Tailscale-scoped exposure, and the deployment
manual is the artifact that makes that control operational. These tests pin the
manual to the posture so a docs edit cannot silently reintroduce an example
that publishes the unauthenticated listener on every interface — the
documentation here is a controlled artifact, and this is its regression test.
"""

import re
from pathlib import Path

import pytest

_DOCS = Path(__file__).resolve().parents[2] / "docs" / "manual" / "admin"


@pytest.mark.req("FRG-DEP-011")
def test_no_deployment_example_publishes_the_port_on_all_interfaces():
    """Every `8789:8789` mapping in the manual must be host-address-prefixed.

    A bare ``-p 8789:8789`` / ``"8789:8789"`` binds 0.0.0.0 on the host —
    exactly the exposure RISK-020's acceptance forbids. Prose may mention the
    bare form only to warn against it (a NOT/would-publish sentence).
    """
    text = (_DOCS / "deployment.md").read_text()
    for lineno, line in enumerate(text.splitlines(), 1):
        for match in re.finditer(r'(\S*)8789:8789', line):
            prefix = match.group(1)
            if prefix.endswith(":"):
                continue  # host-address-prefixed (e.g. 100.x.y.z:8789:8789)
            lowered = line.lower()
            assert "not" in lowered or "would" in lowered, (
                f"deployment.md:{lineno} shows an all-interfaces port mapping "
                f"outside a warning context: {line.strip()!r}"
            )


@pytest.mark.req("FRG-DEP-011")
def test_network_manual_states_the_exposure_rule():
    text = (_DOCS / "network.md").read_text()
    assert "Do not" in text and "public internet" in text, (
        "network.md must carry the explicit do-not-publish warning — it is "
        "the RISK-020 compensating-control statement"
    )
    assert "Tailscale" in text or "tailnet" in text


@pytest.mark.req("FRG-DEP-011")
def test_compose_example_binds_to_a_tailnet_address():
    text = (_DOCS / "deployment.md").read_text()
    assert "100.x.y.z:8789:8789" in text, (
        "the deployment examples must demonstrate the tailnet-address-"
        "prefixed port binding"
    )