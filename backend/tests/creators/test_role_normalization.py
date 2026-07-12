"""Role-string normalization onto the fixed vocabulary (FRG-CRTR-001)."""

from __future__ import annotations

import pytest

from foragerr.metadata.credits import ROLE_VOCABULARY, normalize_role


@pytest.mark.req("FRG-CRTR-001")
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("writer", "writer"),
        ("Writer", "writer"),
        ("  WRITER  ", "writer"),
        ("plotter", "writer"),
        ("scripter", "writer"),
        ("artist", "artist"),
        ("penciler", "penciler"),
        ("penciller", "penciler"),  # CV double-l spelling
        ("inker", "inker"),
        ("colorist", "colorist"),
        ("colourist", "colorist"),  # British spelling
        ("letterer", "letterer"),
        ("cover", "cover"),
        ("cover artist", "cover"),
        ("editor", "editor"),
        ("editor in chief", "editor"),
        ("assistant editor", "other"),  # unknown -> other
        ("designer", "other"),
        ("", "other"),
    ],
)
def test_role_normalization_table(raw, expected):
    normalized = normalize_role(raw)
    assert normalized == expected
    assert normalized in ROLE_VOCABULARY


@pytest.mark.req("FRG-CRTR-001")
def test_every_vocabulary_slot_is_reachable_and_valid():
    # "other" is the fallthrough; the rest each have at least one alias hit
    hits = {
        normalize_role(token)
        for token in (
            "writer",
            "artist",
            "penciler",
            "inker",
            "colorist",
            "letterer",
            "cover",
            "editor",
        )
    }
    hits.add(normalize_role("nonsense-role"))  # -> other
    assert hits == set(ROLE_VOCABULARY)
