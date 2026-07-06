"""SER-008 template ownership transfer (FRG-PP-010).

Change-3's fixed series-folder template is now rendered by the change-6 token
engine. This proves there is no behaviour change for existing rows: the engine's
:func:`render_series_folder` reproduces the exact pre-transfer formula
(``{safe title} ({year})``, year omitted when unknown) over a broad title corpus,
and :func:`foragerr.library.paths.series_folder_name` now delegates to it.
"""

from __future__ import annotations

import random

import pytest

from foragerr.importer.renamer import render_series_folder
from foragerr.library.paths import series_folder_name
from foragerr.security.paths import safe_path_component

SEED = 20260705


def _legacy_formula(title: str, start_year: int | None) -> str:
    """The pre-transfer change-3 implementation, inlined verbatim."""
    safe_title = safe_path_component(title)
    if start_year is None:
        return safe_title
    return f"{safe_title} ({start_year})"


_TITLES = [
    "Batman",
    "Spider-Man: Blue",
    "Amazing Fantasy",
    "X-23",
    "CON",  # reserved device name → de-reserved
    "  leading trailing  ",
    "Weird/Slash\\Title",
    "2000AD",
    "Saga",
    "流浪地球",
    "Issue.Ending.Dots...",
    "NUL.txt",
]


@pytest.mark.req("FRG-PP-010")
def test_engine_matches_change3_formula_over_corpus():
    for title in _TITLES:
        for year in (None, 1939, 1987, 2004, 2026):
            assert render_series_folder(title, year) == _legacy_formula(title, year), (
                title,
                year,
            )


@pytest.mark.req("FRG-PP-010")
def test_library_paths_delegates_to_the_engine():
    for title in _TITLES:
        for year in (None, 1987, 2026):
            assert series_folder_name(title, year) == render_series_folder(title, year)


@pytest.mark.req("FRG-PP-010")
def test_seeded_titles_still_match():
    rng = random.Random(SEED)
    alphabet = "abcdefghijklmnop ABCDEF-.:/\\()½流1234567890"
    for _ in range(2000):
        title = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 40)))
        year = rng.choice([None, 1970, 1999, 2011, 2026])
        assert render_series_folder(title, year) == _legacy_formula(title, year), (
            repr(title),
            year,
        )
