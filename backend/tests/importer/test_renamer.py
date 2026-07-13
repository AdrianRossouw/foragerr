"""Token renaming engine unit tests (FRG-PP-009)."""

from __future__ import annotations

import pytest

from foragerr.importer.renamer import (
    DEFAULT_FILE_TEMPLATE,
    RenameFields,
    render,
    render_filename,
)


@pytest.mark.req("FRG-PP-009")
def test_tokens_padding_and_year_render():
    # Subject: the {IssueId} token renders into the durable identity tag. The
    # shipped default is tag-free (FRG-PP-020), so pin the tagged template
    # explicitly rather than exercising it through DEFAULT_FILE_TEMPLATE.
    fields = RenameFields(series_title="Batman", issue="5", year="1987", issue_id="99")
    assert (
        render_filename(
            fields,
            template="{Series Title} {Issue Number:000} ({Year}) [__{IssueId}__]",
            ext=".cbz",
        )
        == "Batman 005 (1987) [__99__].cbz"
    )


@pytest.mark.req("FRG-PP-009")
def test_padding_is_decimal_safe():
    # 15.5 under {Issue Number:000} pads only the integer part.
    fields = RenameFields(series_title="Invincible", issue="15.5", year="2005")
    out = render_filename(fields, template="{Series Title} {Issue Number:000} ({Year})")
    assert out == "Invincible 015.5 (2005)"


@pytest.mark.req("FRG-PP-009")
def test_named_and_suffix_issues_not_mangled_by_padding():
    assert render(
        "{Issue Number:000}", RenameFields(issue="½")
    ) == "½"
    assert render("{Issue Number:000}", RenameFields(issue="27AU")) == "27AU"


@pytest.mark.req("FRG-PP-009")
def test_optional_group_dropped_when_empty():
    # No issue id -> the whole [__...__] span (brackets included) disappears.
    fields = RenameFields(series_title="Batman", issue="5", year="1987")
    out = render_filename(fields, template=DEFAULT_FILE_TEMPLATE, ext=".cbz")
    assert out == "Batman 005 (1987).cbz"
    # A bracket span with no tokens is literal and always kept.
    assert render("A [HD] B", RenameFields()) == "A [HD] B"


@pytest.mark.req("FRG-PP-009")
def test_token_case_control():
    fields = RenameFields(series_title="Batman")
    assert render("{series title}", fields) == "batman"
    assert render("{SERIES TITLE}", fields) == "BATMAN"
    assert render("{Series Title}", fields) == "Batman"


@pytest.mark.req("FRG-PP-009")
def test_illegal_characters_replaced():
    fields = RenameFields(series_title='Spider-Man: Web/Warriors', issue="1")
    out = render_filename(fields, template="{Series Title} {Issue Number:000}", ext=".cbz")
    assert ":" not in out and "/" not in out
    assert out == "Spider-Man Web Warriors 001.cbz"


@pytest.mark.req("FRG-PP-009")
def test_byte_aware_truncation_keeps_multibyte_intact():
    # A long multibyte title truncated to a small byte ceiling must still decode.
    fields = RenameFields(series_title="流" * 200, issue="1")
    out = render_filename(
        fields,
        template="{Series Title} {Issue Number:000}",
        ext=".cbz",
        max_bytes=40,
    )
    assert len(out.encode("utf-8")) <= 40
    out.encode("utf-8").decode("utf-8")  # no partial code unit — would raise
    assert out.endswith(".cbz")


@pytest.mark.req("FRG-PP-009")
def test_rename_can_be_disabled():
    fields = RenameFields(series_title="Batman", issue="5")
    out = render_filename(
        fields, enabled=False, original="whatever the original was.cbz"
    )
    assert out == "whatever the original was.cbz"
