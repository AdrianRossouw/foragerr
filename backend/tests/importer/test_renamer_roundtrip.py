"""The rename round-trip contract (FRG-PP-009).

Every name this engine renders from a real issue identity must re-parse, via the
single change-2 parser, to the same series matching key and the same issue
ordering key. Seeded stdlib-``random`` variation over template variants (the
convention from ``tests/parser/test_fuzz.py`` — the repo carries no hypothesis
dependency), exercised over the parser regression corpus identities.
"""

from __future__ import annotations

import importlib.util
import random
import sys
from fractions import Fraction
from pathlib import Path

import pytest

from foragerr.importer.renamer import RenameFields, render_filename
from foragerr.library.ordering import encode_sort_key
from foragerr.parser import parse
from foragerr.parser.normalize import matching_key
from foragerr.parser.ordering import sort_key
from foragerr.parser.result import Issue

SEED = 20260705

# Load the parser corpus by file location (it lives in tests/parser, which is on
# sys.path only for that package) without polluting sys.path here.
_corpus_path = Path(__file__).resolve().parent.parent / "parser" / "corpus.py"
_spec = importlib.util.spec_from_file_location("parser_corpus", _corpus_path)
_corpus_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _corpus_mod  # dataclass field introspection needs this
_spec.loader.exec_module(_corpus_mod)
CORPUS = _corpus_mod.CORPUS

# Identity-preserving template variants: dropping/adding the id/cvid/year and
# changing token case never alters the series matching key or the issue ordering
# key. The ``[cvid-{CvIssueId}]`` durable-identity tag (FRG-PP-009) is stripped by
# the parser exactly like ``[__{IssueId}__]``, so it too must leave the round-trip
# identity untouched.
_VARIANTS = (
    "{Series Title} {Issue Number:000} ({Year}) [__{IssueId}__]",
    "{Series Title} {Issue Number:000} ({Year}) [cvid-{CvIssueId}]",
    "{Series Title} {Issue Number:000} ({Year})",
    "{series title} {issue number:000} ({year})",
    "{SERIES TITLE} {ISSUE NUMBER:000} ({YEAR})",
    "{Series Title} {Issue Number:0000}",
)


def _cv_id_for(row) -> str:
    """A plausible, row-stable ComicVine id (disjoint from the internal-id space)."""
    return str(4_000_000 + row.n)


def _eligible(row) -> bool:
    """Scalar-issue corpus identities with a clean series title.

    Excludes the parser's documented year-as-issue special case (FRG-IMP-014):
    when the issue number equals the cover year, a bare ``{Series} {Issue}
    ({Year})`` name is genuinely ambiguous and the parser reclassifies the
    number as title content unless an annual marker is present — that ambiguity
    is the parser's, not the renamer's, so those identities are not part of the
    naive round-trip surface.
    """
    if (
        row.series is None
        or row.issue is None
        or row.display is None
        or row.range_start is not None
        or row.issue_name is not None
    ):
        return False
    if row.year is not None and row.display.strip() == str(row.year):
        return False
    return True


def _expected_order_key(row) -> str:
    """The ordering key of the corpus row's structured issue identity."""
    value = Fraction(row.issue) if row.issue is not None else None
    issue = Issue(value=value, display=row.display or "", suffix=row.suffix)
    return encode_sort_key(sort_key(issue))


def _order_key(issue) -> str:
    return encode_sort_key(sort_key(issue))


@pytest.mark.req("FRG-PP-009")
def test_default_template_round_trips_every_identity():
    checked = 0
    for row in CORPUS:
        if not _eligible(row):
            continue
        checked += 1
        fields = RenameFields(
            series_title=row.series,
            issue=row.display,
            year=str(row.year) if row.year is not None else None,
            issue_id=str(1000 + row.n),
        )
        rendered = render_filename(fields, ext=".cbz")
        reparsed = parse(rendered, reference_year=2026)
        assert reparsed.success, (row.n, rendered)
        assert reparsed.matching_key == matching_key(row.series), (row.n, rendered)
        assert reparsed.issue is not None, (row.n, rendered)
        # Same ordering key as the source issue identity.
        assert _order_key(reparsed.issue) == _expected_order_key(row), (row.n, rendered)
    assert checked >= 40  # the property must actually exercise the corpus


@pytest.mark.req("FRG-PP-009")
def test_oversized_series_title_preserves_identity_tag_and_issue_number():
    """A >255-byte series title must not truncate the round-trip identity away.

    Regression: ``_truncate_bytes`` chopped the whole rendered basename from the
    right, dropping the trailing ``[__{IssueId}__]`` tag (and the issue number)
    when ``{Series Title}`` overran the byte ceiling — so a re-imported file
    could no longer be reconciled back to its issue. The variable title portion
    must be trimmed instead, leaving the id tag + issue number intact.
    """
    issue_id = 987654
    fields = RenameFields(
        series_title="Superlongtitle " * 40,  # ~600 bytes, well over the 255 cap
        issue="404",
        year="1987",
        issue_id=str(issue_id),
    )
    rendered = render_filename(fields, ext=".cbz")

    assert len(rendered.encode("utf-8")) <= 255  # respects the byte ceiling
    assert f"[__{issue_id}__]" in rendered  # identity tag survived truncation
    reparsed = parse(rendered, reference_year=2026)
    assert reparsed.issue_id == str(issue_id)  # reconcilable back to the issue
    assert reparsed.issue is not None
    assert reparsed.issue.display.strip() == "404"  # issue number survived too


@pytest.mark.req("FRG-PP-009")
def test_seeded_template_variants_round_trip():
    rng = random.Random(SEED)
    rows = [r for r in CORPUS if _eligible(r)]
    for _ in range(1500):
        row = rng.choice(rows)
        template = rng.choice(_VARIANTS)
        fields = RenameFields(
            series_title=row.series,
            issue=row.display,
            year=str(row.year) if row.year is not None else None,
            issue_id=str(1000 + row.n),
            cv_issue_id=_cv_id_for(row),
        )
        rendered = render_filename(fields, template=template, ext=".cbz")
        reparsed = parse(rendered, reference_year=2026)
        assert reparsed.success, (row.n, template, rendered)
        assert reparsed.matching_key == matching_key(row.series), (
            row.n,
            template,
            rendered,
        )
        assert reparsed.issue is not None, (row.n, template, rendered)
        assert _order_key(reparsed.issue) == _expected_order_key(row), (
            row.n,
            template,
            rendered,
        )
        # The durable cvid tag round-trips whenever the template carries it.
        if "cvid" in template:
            assert reparsed.cv_issue_id == int(_cv_id_for(row)), (
                row.n,
                template,
                rendered,
            )


@pytest.mark.req("FRG-PP-009")
def test_cvid_variant_round_trips_identity_and_cv_id_over_the_corpus():
    """The ``[cvid-{CvIssueId}]`` template preserves the round-trip identity AND
    recovers the durable ComicVine id for every eligible corpus identity."""
    template = "{Series Title} {Issue Number:000} ({Year}) [cvid-{CvIssueId}]"
    checked = 0
    for row in CORPUS:
        if not _eligible(row):
            continue
        checked += 1
        fields = RenameFields(
            series_title=row.series,
            issue=row.display,
            year=str(row.year) if row.year is not None else None,
            cv_issue_id=_cv_id_for(row),
        )
        rendered = render_filename(fields, template=template, ext=".cbz")
        reparsed = parse(rendered, reference_year=2026)
        assert reparsed.success, (row.n, rendered)
        assert reparsed.matching_key == matching_key(row.series), (row.n, rendered)
        assert reparsed.issue is not None, (row.n, rendered)
        assert _order_key(reparsed.issue) == _expected_order_key(row), (row.n, rendered)
        assert reparsed.cv_issue_id == int(_cv_id_for(row)), (row.n, rendered)
    assert checked >= 40
