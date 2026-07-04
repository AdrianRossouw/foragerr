# Change: m1-filename-parser — the pure comic filename/release-title parser

## Why

Phase 3 change 2 of 7 (approved plan, 2026-07-04). The parser is the single most reused
component in the system — library scan, release-title evaluation, import evidence, and
the rename round-trip all consume it — and it is pure code with no platform
dependencies, so it lands early and in parallel with `m1-foundation`. Mylar's ~1,150-line
stateful `parseit()` (plus four divergent re-implementations) is the defect catalog this
change is designed against.

## What Changes

Implements all 21 parser requirements (FRG-IMP-001..021; no new IDs; scenario
elaboration only):

- **One pure parser** (FRG-IMP-001..003): single implementation for all consumers;
  `parse(name, reference_year=…)` deterministic with no clock/config/network access;
  structured typed result — absent fields are `None` (no sentinels), machine-readable
  failure reasons, confidence score, never raises on any input.
- **Tokenization & normalization** (FRG-IMP-004..006): space/underscore/comma splitting
  (dot-dominant NZB names handled), `(...)`/`[...]` as atomic annotation tokens,
  index-stable positions; Unicode-native (dashes, curly quotes, ½ ¼ ¾) via one
  normalization function; case-insensitive archive-extension recognition.
- **Issue-number grammar** (FRG-IMP-007..011): plain and `#`-prefixed integers with
  leading-title guard; decimals, negatives, Unicode fractions; alphanumeric suffixes
  from a configurable vocabulary (AU/AI/INH/NOW/MU…); named issues; ranges;
  `(of N)` mini-series counts; cover/page-tag stripping.
- **Classification** (FRG-IMP-012..019): volume designators (ordinal vs volume-year,
  roman numerals; `Part N` is not a volume); year/cover-date extraction with
  reference-year plausibility; year-equals-issue one-shot disambiguation;
  annuals/specials as a typed classification enum; booktype enum; generic scan-group and
  edition-tag annotation classification; `[__id__]` pass-through (the DDL snatch
  handshake); series-title output with alternate-title splits.
- **Ordering key** (FRG-IMP-020): total, transitive, collision-free sort key across all
  issue-number forms.
- **Corpus regression suite** (FRG-IMP-021): all 75 corpus rows from
  `docs/research/mylar-filename-parsing.md` §3 asserted as corrected expectations, each
  row tagged to requirement IDs; zero-unhandled-exception fuzz plus a validation sweep
  over the ~4.6k real filenames in the mounted test library.

## Capabilities

### New Capabilities

None — all requirements exist in the approved baseline specs.

### Modified Capabilities

- `imp`: FRG-IMP-001..021 scenario elaboration (delta spec in this change).

## Non-goals

- No library scan walk (FRG-IMP-022, M2), no import staging/review (FRG-IMP-023, M2),
  no embedded-metadata read (FRG-IMP-024, M2), no arc reading-order prefix
  (FRG-IMP-025, B).
- No consumers wired up: series matching, rename round-trip enforcement, and import
  evidence aggregation arrive in changes 3 and 6. This change ships the parser package +
  its test corpus only.
- No parsing of archive *contents* — filenames/release titles only.
- No new attack surface: the parser is pure code over strings (untrusted input handled
  by never crashing; no I/O, no eval, no regex catastrophic backtracking — bounded
  patterns verified in tests). No `docs/security/` delta required.

## Impact

- **New code**: `backend/src/foragerr/parser/` (package: normalize, tokenize, grammar,
  classify, result types, ordering key) + `backend/tests/parser/` (corpus table, unit
  tests, fuzz sweep). Layout matches `tools/trace.py` discovery. If this change merges
  before `m1-foundation`, it creates the minimal `backend/pyproject.toml` skeleton;
  whichever branch merges second rebases trivially — coordinated by the orchestrator.
- **Dependencies**: none beyond Python 3.12 + pytest (pure stdlib implementation).
- **Registry**: on merge, FRG-IMP-001..021 flip `approved → implemented`.

## Approval

- **Status:** Pending owner decision (FRG-PROC-009) — implementation does not start
  until Adrian records approval here.
