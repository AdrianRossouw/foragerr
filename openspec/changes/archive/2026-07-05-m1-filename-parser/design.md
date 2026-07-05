# Design: m1-filename-parser

## Context

The parser is consumed by library scanning, import evidence aggregation, release-title
evaluation, and folder parsing (FRG-IMP-001), and later pinned by SRCH's calling
contract (FRG-SRCH-002) and PP's rename round-trip (FRG-PP-009). The research doc
`docs/research/mylar-filename-parsing.md` (MFP) is the authoritative source: it
catalogs Mylar's ~1,150-line stateful `parseit()` defects (§4), prescribes the quality
bar (§5), and supplies the 75-row corpus (§3) whose *corrected* expectations this
change asserts.

## Goals / Non-Goals

**Goals:** one pure, deterministic, zero-crash parser package with typed results,
data-driven vocabularies, a collision-free ordering key, and the corpus suite at full
strength (FRG-IMP-021 — "full corpus strength IS M1").

**Non-Goals:** library scan walk (M2), import staging (M2), embedded metadata (M2),
wiring any consumer (changes 3/6), archive-content inspection, network/DB access of
any kind.

## Decisions

1. **Pure stdlib package** `foragerr/parser/` — no third-party deps. Modules:
   `normalize.py` (single normalization function, FRG-IMP-005), `tokenize.py`
   (index-stable token stream with atomic `(...)`/`[...]` groups, FRG-IMP-004),
   `vocab.py` (data tables: suffix vocabulary, edition tags, booktype cues, annual
   markers — configurable via an options object, never code branches),
   `grammar.py` (issue/volume/year/count extraction), `classify.py` (annotations,
   scan group, booktype, annual/special), `result.py` (frozen dataclasses + failure
   reasons enum + confidence), `ordering.py` (sort-key tuple), `__init__.py` exposing
   `parse(name, *, reference_year, mode=FILENAME|FOLDER, options=Defaults)`.

2. **Result shape**: frozen `ParseResult` with `series_name`, `matching_key`,
   `alt_series`/`alt_issue_title`, `issue` (value/suffix/display/classification
   record or structured range), `miniseries_total`, `volume_ordinal`, `volume_year`,
   `year`, `booktype` enum, `annotations[]`, `scan_group`, `issue_id`, `type`
   (extension), `confidence`, `failure_reason`, optional `token_trace`. One status
   vocabulary; absent = `None` (FRG-IMP-003).

3. **Pipeline over regex monolith**: normalize → tokenize → strip extension →
   extract `[__id__]` → classify atomic annotation groups → extract count/year/
   volume/suffix candidates → select issue via ordered candidate rules (leading-title
   guard, `#` anchor precedence, `(of N)` override, year-position exclusion, dash
   demotion, rightmost survivor) → assemble title/alt splits → classification +
   booktype → confidence scoring. Each stage is a pure function over the token
   stream; the token trace is the stages' recorded decisions (cheap diagnostics).

4. **Ordering key** (FRG-IMP-020): tuple `(numeric_value: Fraction, class_rank: int,
   suffix_rank: int)` — `Fraction` avoids float-collision, class rank separates
   regular/annual/special domains, suffix rank comes from vocabulary order. Property
   tests assert totality/transitivity/collision-freedom over generated identities.

5. **Corpus as data** (FRG-IMP-021): `backend/tests/parser/corpus.py` — a table of
   rows `(filename, expected fields..., req_ids: tuple[str, ...])` executed by one
   parametrized test that emits each row's FRG tags; `tools/trace.py` sees the IDs in
   the file. Additive-only policy stated in the file header. Fuzz: `random`-seeded
   generative sweep (printable/control/astral Unicode, huge names) asserting only
   "returns ParseResult, never raises". Real-world sweep: env-gated test
   (`FORAGERR_CORPUS_DIR`) walking a filename list harvested from the mounted library
   (read-only), asserting the zero-crash bar; a committed fixture list of ~500
   representative names (no personal data concerns — filenames only) runs in CI
   unconditionally.

6. **Bounded regexes**: no nested quantifiers over user-controlled spans; every
   pattern reviewed for catastrophic backtracking; fuzz includes pathological inputs
   (e.g. 10k dashes) with a wall-clock ceiling per parse.

7. **Coordination with m1-foundation**: whichever branch merges second rebases onto
   the minimal `backend/pyproject.toml` from the first — the parser package has no
   import edge into the platform code, so the merge is directory-disjoint apart from
   that one file.

## Risks / Trade-offs

- [Corrected expectations diverge from Mylar behavior] → the corpus asserts MFP §3's
  *desired* column; divergences are deliberate and documented per-row (rows 25, 42,
  43, 50, 58 explicitly pinned).
- [Confidence scoring is heuristic] → spec only requires anchored > ambiguous
  discrimination; the exact scale is an implementation detail consumers must not
  couple to (documented in result.py).
- [Vocabulary gaps (unknown suffixes)] → vocabulary is options-supplied data; gaps
  degrade to title content (safe direction), and corpus growth policy covers fixes.

## Migration Plan

Greenfield package; no consumers yet. Rollback = don't merge the branch.

## Open Questions

None blocking.

## Known limitations

Accepted M1 behaviors, documented rather than fixed:

- **Fully hyphen-glued names lose genuine title hyphens.** A name with no other
  separators and 2+ hyphens (e.g. `X-23-005-2020.cbr`) is hyphen-tokenized, so a
  genuinely hyphenated title has its hyphen split away and `series_name` degrades
  to `X 23`. This does not affect series matching: the `matching_key` folds
  punctuation, so `X-23` and `X 23` collapse to the same key. Accepted for M1.
- **`matching_key` folds `and`/`&` together by design.** The conjunction is folded
  so `Foo & Bar` and `Foo and Bar` release-name variants match the same series.
  A side effect is that two genuinely distinct titles differing *only* by the
  conjunction collide on `matching_key`. Accepted: library identity is the
  ComicVine volume id, not the matching key, and CV-mapping ties break on
  year/volume — the key is only a coarse candidate filter.
