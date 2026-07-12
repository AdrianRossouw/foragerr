"""Comic-vs-other classification rule (FRG-SRC-003, design decision 4)."""

from __future__ import annotations

import pytest

from foragerr.sources.classify import DownloadOption, classify, preferred_option


def _opt(fmt: str, platform: str = "ebook") -> DownloadOption:
    return DownloadOption(
        format=fmt, platform=platform, md5=None, file_size=None, filename=None
    )


@pytest.mark.req("FRG-SRC-003")
def test_cbz_pdf_twins_classify_comic_prefer_cbz():
    options = [_opt("CBZ"), _opt("PDF")]
    assert classify(options) == "comic"
    preferred = preferred_option(options)
    assert preferred is not None and preferred.format == "CBZ"


@pytest.mark.req("FRG-SRC-003")
def test_cbr_only_classifies_comic():
    assert classify([_opt("CBR")]) == "comic"


@pytest.mark.req("FRG-SRC-003")
def test_epub_only_classifies_other():
    assert classify([_opt("EPUB")]) == "other"
    assert preferred_option([_opt("EPUB")]) is None


@pytest.mark.req("FRG-SRC-003")
def test_pdf_only_classifies_comic_ogn_artbook():
    # A PDF with no prose sibling is a PDF-only OGN/artbook -> comic.
    options = [_opt("PDF")]
    assert classify(options) == "comic"
    assert preferred_option(options).format == "PDF"


@pytest.mark.req("FRG-SRC-003")
def test_pdf_with_prose_sibling_classifies_other():
    # A PDF that ships alongside EPUB/MOBI is a prose ebook -> other.
    assert classify([_opt("PDF"), _opt("EPUB")]) == "other"
    assert classify([_opt("PDF"), _opt("MOBI")]) == "other"


@pytest.mark.req("FRG-SRC-003")
def test_non_ebook_platform_classifies_other():
    # A game download (platform != ebook) is never a comic even if the label
    # happened to look archive-ish.
    assert classify([_opt("CBZ", platform="windows")]) == "other"


@pytest.mark.req("FRG-SRC-003")
def test_no_options_classifies_other():
    assert classify([]) == "other"
