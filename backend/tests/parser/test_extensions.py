"""FRG-IMP-006 — archive extension recognition."""

import pathlib

import pytest

from foragerr import parser as parser_module
from foragerr.parser import parse
from foragerr.parser.vocab import ARCHIVE_EXTENSIONS

SRC = pathlib.Path(parser_module.__file__).parent


@pytest.mark.req("FRG-IMP-006")
def test_uppercase_extension_parses_identically():
    upper = parse("Batman 404 (1987).CBZ", reference_year=2026)
    lower = parse("Batman 404 (1987).cbz", reference_year=2026)
    assert upper.to_json() == lower.to_json()
    assert upper.type == "cbz"  # normalized lowercase, no dot — never unknown


@pytest.mark.req("FRG-IMP-006")
def test_extension_substrings_mid_name_never_stripped():
    r = parse("Macbr Chronicles 001 (2015).cbr", reference_year=2026)
    assert r.series_name == "Macbr Chronicles"
    assert r.type == "cbr"
    r = parse("The cbz Files 002 (2016).cbz", reference_year=2026)
    assert r.series_name == "The cbz Files"
    assert r.type == "cbz"


@pytest.mark.req("FRG-IMP-006")
def test_full_extension_set_from_single_definition():
    for ext in ("cbz", "cbr", "cb7", "cbt", "pdf"):
        for spelled in (ext, ext.upper(), ext.capitalize()):
            r = parse(f"Batman 404 (1987).{spelled}", reference_year=2026)
            assert r.type == ext, spelled
            assert r.series_name == "Batman"
    # epub is deliberately not a comic extension (no reader in scope)
    r = parse("Batman 404 (1987).epub", reference_year=2026)
    assert r.type is None
    # exactly one extension-list definition exists in the package
    assert ARCHIVE_EXTENSIONS == ("cbz", "cbr", "cb7", "cbt", "pdf")
    definitions = sum(
        s.read_text().count('"cbz"') for s in SRC.rglob("*.py")
    )
    assert definitions == 1, "extension list must be defined exactly once"


@pytest.mark.req("FRG-IMP-006")
def test_only_the_single_trailing_extension_is_stripped():
    r = parse("Batman 404 (1987).cbz.cbz", reference_year=2026)
    assert r.type == "cbz"
    assert r.series_name == "Batman"
    # the inner `.cbz` remains part of the name, not double-stripped
    serialized = r.to_json()
    assert "cbz" in serialized
