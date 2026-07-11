"""sanitize_cv_text: untrusted ComicVine strings reduced to safe plain text
(FRG-META-014, FRG-NFR-012)."""

from __future__ import annotations

import pytest

from foragerr.metadata.sanitize import MAX_TEXT_LENGTH, sanitize_cv_text


@pytest.mark.req("FRG-META-014")
@pytest.mark.req("FRG-NFR-012")
def test_script_body_is_dropped_entirely():
    out = sanitize_cv_text("<p>Hello</p><script>alert('xss')</script> world")
    assert out is not None
    assert "alert" not in out
    assert "<script" not in out.lower()
    assert "Hello" in out and "world" in out


@pytest.mark.req("FRG-META-014")
def test_tags_stripped_and_entities_decoded():
    out = sanitize_cv_text("Tom <b>&amp;</b> Jerry &lt;3")
    assert out == "Tom & Jerry <3"


@pytest.mark.req("FRG-META-014")
def test_block_tags_do_not_fuse_adjacent_words():
    assert sanitize_cv_text("<p>one</p><p>two</p>") == "one two"


@pytest.mark.req("FRG-NFR-012")
def test_whitespace_collapsed_and_trimmed():
    assert sanitize_cv_text("  a\t\t b\n\n c  ") == "a b c"


@pytest.mark.req("FRG-NFR-012")
def test_ansi_and_control_characters_stripped():
    hostile = "safe\x1b[31mRED\x1b[0m\x00\x07 line\r\nforged: log"
    out = sanitize_cv_text(hostile)
    assert "\x1b" not in out
    assert "\x00" not in out and "\x07" not in out
    assert "\r" not in out and "\n" not in out
    assert "safeRED line forged: log" == out


@pytest.mark.req("FRG-NFR-012")
def test_length_capped():
    out = sanitize_cv_text("x" * (MAX_TEXT_LENGTH + 5000))
    assert out is not None and len(out) <= MAX_TEXT_LENGTH


@pytest.mark.req("FRG-META-014")
def test_non_ascii_preserved():
    assert sanitize_cv_text("Amélie — naïve café ½") == "Amélie — naïve café ½"


@pytest.mark.req("FRG-META-014")
def test_empty_or_html_only_becomes_none():
    assert sanitize_cv_text(None) is None
    assert sanitize_cv_text("") is None
    assert sanitize_cv_text("<script>only()</script>") is None
    assert sanitize_cv_text("   \x00  ") is None


@pytest.mark.req("FRG-NFR-012")
def test_malformed_markup_never_raises():
    # Unbalanced/garbage markup must degrade, never raise.
    assert sanitize_cv_text("<a href='<<>'>>text<<</b") is not None


@pytest.mark.req("FRG-META-014")
def test_bidi_override_and_zero_width_chars_are_stripped():
    """Trojan-Source-class visual-spoofing controls in CV wiki text (bidi
    overrides/isolates, zero-width joiners, BOM) must not survive to a render
    surface, where they could reverse or hide the displayed string
    (RISK-011/014). Surfaced by the m4-add-new adversarial gate."""
    hostile = (
        "Saga"
        "‮" "reversed" "‬"   # RLO ... PDF
        "⁦" "isolate" "⁩"    # LRI ... PDI
        "​" "zero‍width"     # ZWSP, ZWJ
        "⁠" "﻿" "؜"     # word-joiner, BOM, ALM
    )
    out = sanitize_cv_text(hostile)
    assert out is not None
    for cp in (0x061C, 0x200B, 0x200D, 0x200E, 0x200F,
               0x202A, 0x202E, 0x2060, 0x2066, 0x2069, 0xFEFF):
        assert chr(cp) not in out, f"leaked U+{cp:04X}"
    # legitimate content survives — only the invisible controls are removed
    assert "Saga" in out and "reversed" in out and "isolate" in out


@pytest.mark.req("FRG-META-014")
def test_ordinary_hyphenated_title_is_unchanged():
    # guard: the bidi/zero-width strip must not touch normal punctuation
    assert sanitize_cv_text("Spider-Man 2099") == "Spider-Man 2099"
