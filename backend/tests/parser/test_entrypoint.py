"""FRG-IMP-001 — single parser implementation for all consumers."""

import pathlib

import pytest

from foragerr import parser as parser_module
from foragerr.parser import ParseMode, parse

SRC = pathlib.Path(parser_module.__file__).parent


@pytest.mark.req("FRG-IMP-001")
def test_filename_and_release_title_share_the_entry_point():
    fn = parse(
        "Invincible Iron Man 019 (2016) (Digital) (Minutemen-Faessla).cbz",
        reference_year=2026,
    )
    rt = parse(
        "Invincible Iron Man 019 (2016) (Digital) (Minutemen-Faessla)",
        reference_year=2026,
    )
    # both calls resolve to the same function object in the same module
    assert parse is parser_module.parse
    assert fn.series_name == rt.series_name == "Invincible Iron Man"
    assert fn.issue == rt.issue and fn.issue.value == 19
    assert fn.year == rt.year == 2016
    assert fn.scan_group == rt.scan_group == "Minutemen-Faessla"
    assert fn.type == "cbz" and rt.type is None
    # field-for-field identical except the extension-derived type field
    fd, rd = fn.to_dict(), rt.to_dict()
    fd.pop("type"), rd.pop("type")
    assert fd == rd


@pytest.mark.req("FRG-IMP-001")
def test_folder_mode_reuses_the_engine():
    r = parse("Batman (2016)", reference_year=2026, mode=ParseMode.FOLDER)
    assert r.series_name == "Batman"
    assert r.year == 2016
    assert r.issue is None
    assert r.type is None
    assert r.failure_reason is None
    # same result shape: the folder-mode result is a ParseResult like any other
    assert set(r.to_dict()) == set(
        parse("Batman 404 (1987).cbz", reference_year=2026).to_dict()
    )


@pytest.mark.req("FRG-IMP-001")
def test_import_graph_has_exactly_one_parser_implementation():
    """No duplicate tokenization / parse / issue-normalization logic."""
    sources = list(SRC.rglob("*.py"))
    assert sources, "parser package sources not found"

    def count_defs(name: str) -> int:
        return sum(s.read_text().count(f"def {name}(") for s in sources)

    assert count_defs("tokenize") == 1
    assert count_defs("parse") == 1
    assert count_defs("matching_key") == 1
    assert count_defs("sort_key") == 1
