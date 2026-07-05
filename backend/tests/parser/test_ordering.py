"""FRG-IMP-020 — total, collision-free issue ordering keys."""

import ast
import pathlib
import random
from fractions import Fraction

import pytest

from foragerr import parser as parser_module
from foragerr.parser import DEFAULT_OPTIONS, Issue, IssueClassification, parse, sort_key

SRC = pathlib.Path(parser_module.__file__).parent


def _issue(value=None, suffix=None, cls=IssueClassification.REGULAR, inf=False, name=None):
    return Issue(
        value=None if value is None else Fraction(value),
        display=str(value),
        suffix=suffix,
        classification=cls,
        is_infinity=inf,
        name=name,
    )


@pytest.mark.req("FRG-IMP-020")
def test_mixed_vocabulary_values_sort_in_expected_order():
    parsed = [
        parse(n, reference_year=2026).issue
        for n in (
            "Deadpool -1 (1997).cbz",
            "Uncanny X-Men ½ (1999).cbz",
            "Amazing Spider-Man 015A (2014).cbz",
            "Invincible 015.5 (2005).cbz",
            "Wolverine 027AU (2013).cbz",
        )
    ]
    ordered = sorted(parsed, key=sort_key)
    assert [i.display for i in ordered] == ["-1", "½", "015A", "015.5", "027AU"]
    # a fraction glyph and a plain 0.5 denote the same issue identity
    assert sort_key(_issue("1/2")) == sort_key(parse("Uncanny X-Men ½ (1999).cbz", reference_year=2026).issue)
    # ...but 15A and plain 15 are distinct, deterministically ordered
    assert sort_key(_issue(15)) < sort_key(_issue(15, suffix="A"))


@pytest.mark.req("FRG-IMP-020")
def test_distinct_suffixes_never_collide():
    suffixes = [None] + list(DEFAULT_OPTIONS.issue_suffixes) + list(
        DEFAULT_OPTIONS.single_letter_suffixes
    )
    bases = ["-1", "0", "1/2", "1", "15", "15.5", "27", "600", "202004"]
    identities = [
        _issue(b, suffix=s, cls=c)
        for b in bases
        for s in suffixes
        for c in IssueClassification
    ]
    keys = [sort_key(i) for i in identities]
    assert len(set(keys)) == len(identities), "ordering keys collided"
    # equal-ord-sum suffix pairs (AB vs BA) stay distinct under an extended
    # vocabulary — no ord-sum scoring anywhere
    opts = DEFAULT_OPTIONS.with_suffixes("AB", "BA")
    assert sum(map(ord, "AB")) == sum(map(ord, "BA"))
    a = sort_key(_issue(5, suffix="AB"), opts)
    b = sort_key(_issue(5, suffix="BA"), opts)
    assert a != b


@pytest.mark.req("FRG-IMP-020")
def test_total_order_properties_and_single_implementation():
    rng = random.Random(20260704)
    values = ["-3", "-1", "0", "1/2", "1", "2", "15", "15.5", "27", "1997"]
    pool = [
        _issue(v, suffix=s, cls=c, inf=False)
        for v in values
        for s in (None, "AU", "NOW", "A")
        for c in (IssueClassification.REGULAR, IssueClassification.ANNUAL)
    ] + [_issue(None, inf=True), _issue(None, name="Alpha"), _issue(None, name="Omega")]
    for _ in range(500):
        x, y, z = (rng.choice(pool) for _ in range(3))
        kx, ky, kz = sort_key(x), sort_key(y), sort_key(z)
        # totality: every pair comparable
        assert kx <= ky or ky <= kx
        # reflexive-antisymmetric
        assert kx <= kx
        if kx <= ky and ky <= kx:
            assert kx == ky
        # transitive
        if kx <= ky and ky <= kz:
            assert kx <= kz
    # annual #1 and regular #1 have distinct, deterministically ordered keys
    regular = _issue(1)
    annual = _issue(1, cls=IssueClassification.ANNUAL)
    assert sort_key(regular) != sort_key(annual)
    assert sort_key(regular) < sort_key(annual)
    # exactly one ordering implementation exists
    count = sum(s.read_text().count("def sort_key(") for s in SRC.rglob("*.py"))
    assert count == 1


@pytest.mark.req("FRG-IMP-020")
def test_no_sentinel_or_magnitude_mixing():
    # infinity sorts after every finite issue, without magic numbers
    finite = [_issue(v) for v in ("-1", "0", "999999", "202004")]
    inf = _issue(None, inf=True)
    for i in finite:
        assert sort_key(i) < sort_key(inf)
    # no numeric sentinel constant anywhere in the code (docstrings may
    # cite Mylar's sentinel by name; the logic must never use it)
    for source in SRC.rglob("*.py"):
        tree = ast.parse(source.read_text())
        numbers = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, int)
        ]
        assert 999999999999999 not in numbers
        assert 9999999999 not in numbers
