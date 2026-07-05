"""FRG-IMP-017 — generic annotation classification (scan groups, editions)."""

import ast
import pathlib

import pytest

from foragerr import parser as parser_module
from foragerr.parser import parse

SRC = pathlib.Path(parser_module.__file__).parent


def _code_string_constants(path: pathlib.Path) -> list[str]:
    """String constants in the code, excluding docstrings (prose may cite
    Mylar's hacks; the *logic* must not consult them)."""
    tree = ast.parse(path.read_text())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
            ):
                docstrings.add(id(node.body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


@pytest.mark.req("FRG-IMP-017")
def test_known_style_groups_extracted_by_the_generic_rule():
    cases = {
        "Justice League Dark 016 (2019) (Webrip) (The Last Kryptonian-DCP).cbz": "The Last Kryptonian-DCP",
        "Invincible Iron Man 019 (2016) (Digital) (Minutemen-Faessla).cbz": "Minutemen-Faessla",
        "Southern Bastards 09 (2015) (digital) (Son of Ultron-Empire).cbr": "Son of Ultron-Empire",
    }
    for name, group in cases.items():
        assert parse(name, reference_year=2026).scan_group == group, name
    # audit: no hardcoded ripper-substring list is consulted for correctness
    for source in SRC.rglob("*.py"):
        for constant in _code_string_constants(source):
            for ripper in ("minutemen", "glorith", "-dcp", "kryptonian", "-empire"):
                assert ripper not in constant.lower(), (source.name, ripper)


@pytest.mark.req("FRG-IMP-017")
def test_unknown_groups_are_captured_too():
    r = parse("Black Hammer 07 (2017) (Oroboros).cbz", reference_year=2026)
    assert r.scan_group == "Oroboros"  # structural, not vocabulary-driven


@pytest.mark.req("FRG-IMP-017")
@pytest.mark.req("FRG-IMP-015")
def test_glorith_dot_name_passes_via_generic_rules():
    r = parse("Batman.Annual.02.2017.digital.Glorith-HD.cbz", reference_year=2026)
    assert r.series_name == "Batman"
    assert r.issue.classification.value == "annual"
    assert r.issue.value == 2
    assert r.year == 2017
    tags = {(a.kind.value, a.text) for a in r.annotations}
    assert ("edition", "digital") in tags
    assert r.scan_group == "Glorith-HD"


@pytest.mark.req("FRG-IMP-017")
def test_edition_tags_never_leak_or_become_scan_groups():
    for name in (
        "Saga 55 (2018) (digital) (36p ctc).cbz",
        "Monstress Vol. 06 (2021) (Digital) TPB.cbz",
        "Lazarus 01 (2013) [1920px].cbz",
    ):
        r = parse(name, reference_year=2026)
        assert r.scan_group is None, name
        for word in ("digital", "Digital", "ctc", "1920px"):
            assert word not in (r.series_name or ""), name
            if r.issue:
                assert word not in r.issue.display, name
        assert r.volume_year is None, name
    tags = {
        a.kind.value
        for a in parse(
            "Lazarus 01 (2013) [1920px].cbz", reference_year=2026
        ).annotations
    }
    assert "page-tag" in tags


@pytest.mark.req("FRG-IMP-017")
def test_scan_group_requires_alphabetic_content():
    r = parse("Batman 404 [123456] (1987).cbz", reference_year=2026)
    assert r.scan_group is None
    assert ("generic", "123456") in {(a.kind.value, a.text) for a in r.annotations}
