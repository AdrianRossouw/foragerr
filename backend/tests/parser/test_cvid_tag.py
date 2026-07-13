"""FRG-PP-009 — the durable ``[cvid-<ID>]`` ComicVine identity tag.

The ``{CvIssueId}`` naming token renders ``[cvid-<ID>]``; the parser recognizes
that exact form into ``ParseResult.cv_issue_id`` (a field distinct from the
internal-row-id ``issue_id`` tag), so a rendered name round-trips its durable
ComicVine identity.
"""

import pytest

from foragerr.naming import RenameFields, render, render_filename
from foragerr.parser import parse

_TEMPLATE = "{Series Title} {Issue Number:000} ({Year}) {CvIssueId}"


@pytest.mark.req("FRG-PP-009")
def test_render_with_cvissueid_round_trips_the_cv_id():
    """render({CvIssueId}) → re-parse recovers the same ComicVine id."""
    fields = RenameFields(
        series_title="Saga", issue="5", year="2012", cv_issue_id="145600"
    )
    rendered = render(_TEMPLATE, fields)
    assert rendered == "Saga 005 (2012) [cvid-145600]"

    reparsed = parse(rendered + ".cbz", reference_year=2026)
    assert reparsed.cv_issue_id == 145600  # durable identity round-trips
    assert reparsed.issue_id is None  # never overloads the internal-id tag
    assert reparsed.series_name == "Saga"
    assert reparsed.issue.value == 5
    assert reparsed.year == 2012


@pytest.mark.req("FRG-PP-009")
def test_cvid_tag_recognized_anywhere_and_stripped_from_title():
    lead = parse("[cvid-98765] Batman 404 (1987).cbz", reference_year=2026)
    trail = parse("Batman 404 (1987) [cvid-98765].cbz", reference_year=2026)
    for r in (lead, trail):
        assert r.cv_issue_id == 98765
        assert r.series_name == "Batman"
        assert r.issue.value == 404
        assert "98765" not in (r.series_name or "")
        assert all("98765" not in a.text for a in r.annotations)


@pytest.mark.req("FRG-PP-009")
def test_cvid_tag_is_case_insensitive():
    r = parse("Saga 5 (2012) [CVID-145600].cbz", reference_year=2026)
    assert r.cv_issue_id == 145600


@pytest.mark.req("FRG-PP-009")
def test_absent_cvid_tag_is_none_and_plain_or_internal_tags_are_not_cvids():
    # No tag at all.
    assert parse("Batman 404 (1987).cbz", reference_year=2026).cv_issue_id is None
    # The internal-row-id tag is a distinct namespace — never a cv id.
    internal = parse("Batman 404 (1987) [__404__].cbz", reference_year=2026)
    assert internal.cv_issue_id is None
    assert internal.issue_id == "404"
    # A bare bracketed number is not the cvid convention.
    assert parse("Batman 404 [145600] (1987).cbz", reference_year=2026).cv_issue_id is None


@pytest.mark.req("FRG-PP-009")
def test_empty_cvid_group_is_dropped_when_the_issue_has_no_cv_id():
    """Optional-group semantics: no cv id ⇒ the ``[cvid-…]`` group vanishes."""
    fields = RenameFields(
        series_title="Saga", issue="5", year="2012", cv_issue_id=None
    )
    # render_filename is the real file path: it collapses the separator left by
    # the dropped optional group.
    rendered = render_filename(fields, template=_TEMPLATE, ext=".cbz")
    assert rendered == "Saga 005 (2012).cbz"
    assert "cvid" not in rendered
    assert parse(rendered, reference_year=2026).cv_issue_id is None
