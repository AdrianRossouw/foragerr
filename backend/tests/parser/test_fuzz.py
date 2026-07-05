"""FRG-IMP-003 / FRG-IMP-021 — zero-crash fuzz sweep with a wall-clock ceiling.

Seeded stdlib ``random`` generation (no third-party property-testing dep):
arbitrary Unicode including control characters, lone surrogates, astral
planes, lone brackets, pathological dash/paren/hash runs, huge digit runs,
and multi-megabyte names. Every input must return a structured ParseResult —
success or reasoned failure — with zero unhandled exceptions, inside a
per-parse time ceiling (bounded-regex guarantee).
"""

import random
import time

import pytest
from corpus import CORPUS

from foragerr.parser import ParseMode, ParseResult, parse

SEED = 20260704


def _ceiling(name: str) -> float:
    # generous CI ceiling, scaled for multi-megabyte inputs (linear pipeline)
    return 1.0 + 4.0 * (len(name) / 1_000_000)


def _check(name: str):
    start = time.perf_counter()
    result = parse(name, reference_year=2026)
    elapsed = time.perf_counter() - start
    assert isinstance(result, ParseResult)
    assert result.success or result.failure_reason is not None
    assert elapsed < _ceiling(name), f"parse took {elapsed:.2f}s for {name[:60]!r}"
    return result


@pytest.mark.req("FRG-IMP-003")
@pytest.mark.req("FRG-IMP-021")
def test_arbitrary_unicode_never_crashes():
    rng = random.Random(SEED)
    generators = [
        lambda: "".join(chr(rng.randint(0, 0x10FFFF)) for _ in range(rng.randint(0, 120))),
        lambda: "".join(chr(rng.randint(0, 0x1F)) for _ in range(rng.randint(1, 60))),
        lambda: "".join(chr(rng.randint(0xD800, 0xDFFF)) for _ in range(rng.randint(1, 20))),
        lambda: "".join(
            rng.choice("()[]#-_.,½¼¾∞—–'\" \t") for _ in range(rng.randint(1, 200))
        ),
        lambda: " ".join(str(rng.randint(-(10**12), 10**12)) for _ in range(rng.randint(1, 30))),
    ]
    for _ in range(2000):
        _check(rng.choice(generators)())


@pytest.mark.req("FRG-IMP-003")
def test_pathological_shapes_stay_within_the_ceiling():
    cases = [
        "-" * 10_000,
        " - " * 5_000,
        "(" * 5_000,
        ")" * 5_000,
        "[" * 5_000 + "]" * 5_000,
        "#" * 5_000,
        "9" * 100_000,
        "1-2 " * 4_000,
        "1.2.3." * 3_000,
        "of " * 5_000,
        "v" * 5_000 + "1",
        "A" * 3_000_000,
        ("Batman 404 (1987) " * 20_000) + ".cbz",
        "½" * 10_000,
    ]
    for name in cases:
        _check(name)
        _check(name + ".cbz")


@pytest.mark.req("FRG-IMP-003")
def test_corpus_rows_and_modes_never_crash():
    for row in CORPUS:
        _check(row.filename)
        r = parse(row.filename, reference_year=2026, mode=ParseMode.FOLDER)
        assert isinstance(r, ParseResult)


@pytest.mark.req("FRG-IMP-003")
def test_lone_brackets_and_mixed_garbage():
    for name in (
        "[", "]", "(", ")", "[__", "__]", "[____]", "[__ __]",
        "#", "-", "—", ".", "..", "...cbz", "½", "∞", "of", "(of )",
        "vol", "vol.", "volume", "annual", "tpb", "cover",
        "\x00\x01\x02.cbz", "𐏿", "𝔅𝔞𝔱𝔪𝔞𝔫 404 (1987).cbz",
    ):
        _check(name)
