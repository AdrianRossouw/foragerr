"""Total, collision-free issue ordering keys (FRG-IMP-020).

The single ordering implementation for parsing, matching, sorting, and
renaming. The key is a tuple — no scalar magnitude mixing, no ord-sum
scoring, no ``999999999999999`` sentinels:

    (infinity_rank, numeric_value, class_rank, suffix_vocab_rank,
     suffix_text, name_text)

* ``numeric_value`` is an exact Fraction (float collisions impossible).
* ``class_rank`` separates regular/annual/biannual/special domains, so an
  annual #1 and a regular #1 have distinct, deterministically ordered keys.
* ``suffix_vocab_rank`` orders known suffixes by vocabulary position;
  ``suffix_text`` breaks ties for unknown suffixes, so distinct suffixes can
  never collide (including pairs with equal character-ord sums).
* Named issues are distinguished by ``name_text``.

Tuples give totality and transitivity by construction; property tests assert
both plus collision-freedom across generated identities.
"""

from __future__ import annotations

from fractions import Fraction

from .result import Issue, IssueClassification
from .vocab import DEFAULT_OPTIONS, ParseOptions, suffix_vocab_order

_CLASS_RANK = {
    IssueClassification.REGULAR: 0,
    IssueClassification.ANNUAL: 1,
    IssueClassification.BIANNUAL: 2,
    IssueClassification.SPECIAL: 3,
}

SortKey = tuple[int, Fraction, int, int, str, str]


def sort_key(issue: Issue, options: ParseOptions = DEFAULT_OPTIONS) -> SortKey:
    """Compute the total-order sort key for an issue identity."""
    infinity_rank = 1 if issue.is_infinity else 0
    value = issue.value if issue.value is not None else Fraction(0)
    class_rank = _CLASS_RANK[issue.classification]
    if issue.suffix is None:
        suffix_rank, suffix_text = -1, ""
    else:
        canonical = issue.suffix.upper()
        vocab = suffix_vocab_order(options)
        suffix_rank = vocab.index(canonical) if canonical in vocab else len(vocab)
        suffix_text = canonical
    name_text = issue.name.casefold() if issue.name is not None else ""
    return (infinity_rank, value, class_rank, suffix_rank, suffix_text, name_text)
