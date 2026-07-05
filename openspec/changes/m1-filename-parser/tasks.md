# Tasks

## 1. Package skeleton and result types

- [x] 1.1 Create `backend/src/foragerr/parser/` package (and minimal `backend/pyproject.toml` if m1-foundation has not merged yet) with `result.py`: frozen `ParseResult`, issue record (value/suffix/display/classification), structured range, failure-reason enum, confidence field, optional token trace (FRG-IMP-003)
- [x] 1.2 `normalize.py`: single Unicode-native normalization function (NFC/NFKD comparison, dash/quote folding, article handling, case/separator collapsing) exposed as the one matching-key source (FRG-IMP-005)
- [x] 1.3 `vocab.py`: data-driven vocabularies — suffix exceptions (AU/AI/INH/NOW/BEY/MU/HU/LR/DEATHS/ALPHA/OMEGA/seasonal/Director's Cut), edition tags, booktype cues, annual markers, extension list (single definition), all overridable via an options object (FRG-IMP-006, FRG-IMP-009, FRG-IMP-016, FRG-IMP-017)

## 2. Tokenization and grammar

- [x] 2.1 `tokenize.py`: space/underscore/comma splitting, dot-dominant detection, atomic `(...)`/`[...]` groups, index-stable positions (FRG-IMP-004)
- [x] 2.2 Extension stripping (single trailing, case-insensitive) and `[__<id>__]` extraction anywhere in the name (FRG-IMP-006, FRG-IMP-018)
- [x] 2.3 `grammar.py` issue candidates: plain/zero-padded integers, `#` anchor precedence (incl. detached `#`), leading-title guard, decimals/negatives/Unicode fractions/`∞`, alphanumeric suffixes in glued/space/dotted forms with single-letter guards, named `#`-anchored issues, ranges (structured or diagnostic), `(of N)` counts incl. decimals, cover/page-tag exclusion (FRG-IMP-007, FRG-IMP-008, FRG-IMP-009, FRG-IMP-010, FRG-IMP-011)
- [x] 2.4 Volume designators: v/vol/volume spellings, glued, roman numerals, volume-year and year-range forms, ordinal-vs-year distinct fields, `Part N` exclusion (FRG-IMP-012)
- [x] 2.5 Year/cover-date extraction: parenthesized/bare/ISO/month-name forms, right-most plausible preference, title-region exclusion, reference-year future cutoff, `%Y%m` false-positive guard, 1900–2099 support (FRG-IMP-013)

## 3. Classification and assembly

- [x] 3.1 Issue-candidate selection rules (rightmost survivor, `(of N)` override, year-position exclusion, dash demotion) and year-equals-issue one-shot rule with annual-marker precedence (FRG-IMP-007, FRG-IMP-014)
- [x] 3.2 Annual/BiAnnual/Special structured classification with marker removal and year-annual forms (FRG-IMP-015)
- [x] 3.3 Booktype enum (issue/TPB/GN/HC/one-shot), multi-word matching, trade-volume interpretation with explicit-trade-only v1 default (FRG-IMP-016)
- [x] 3.4 Generic annotation classification: edition/quality tags, generic trailing scan-group rule (no hardcoded correctness list) (FRG-IMP-017)
- [x] 3.5 Title assembly: raw `series_name` minus consumed designators, folded matching key, alternate series/issue-title splits with in-word-hyphen safety (FRG-IMP-019)
- [x] 3.6 `parse()` entry point: pure function, `reference_year` + mode flag + options, no clock/config/DB imports (static guard test), confidence scoring, token trace (FRG-IMP-001, FRG-IMP-002, FRG-IMP-003)

## 4. Ordering key

- [x] 4.1 `ordering.py`: sort-key tuple (Fraction numeric, class rank, suffix rank); property tests for totality, transitivity, zero collisions across generated identity pairs incl. equal-ord-sum suffixes and annual-vs-regular (FRG-IMP-020)

## 5. Corpus and quality gates

- [x] 5.1 `backend/tests/parser/corpus.py`: all 75 MFP §3 rows as data with per-row FRG-IMP tags and corrected expectations (rows 25, 42, 43, 50, 58 pinned); parametrized executor test (FRG-IMP-021)
- [x] 5.2 Unit tests per grammar/classification area tagged to their FRG IDs, including adversarial cases ((of infinity), extension substrings mid-name, sentinel-substring titles, repeated tokens, two-`#` names) (FRG-IMP-004..020)
- [x] 5.3 Zero-crash fuzz sweep (arbitrary Unicode incl. control chars, unpaired surrogates, multi-megabyte names, pathological dash runs with per-parse wall-clock ceiling) (FRG-IMP-003, FRG-IMP-021)
- [x] 5.4 Real-world sweep: committed ~500-name fixture list in CI + env-gated (`FORAGERR_CORPUS_DIR`) zero-crash sweep over the mounted library's ~4.6k filenames, read-only (FRG-IMP-021)

## 6. Traceability and merge gate

- [x] 6.1 Verify every FRG-IMP-001..021 has ≥1 passing tagged test; flip the 21 registry rows to `implemented`; regenerate matrix via `tools/trace.py` (exit 0) (FRG-PROC-004, FRG-PROC-005)
- [x] 6.2 Full suite green; `--no-ff` merge to main (coordinating the shared `backend/pyproject.toml` with m1-foundation, whichever merges second rebases); archive change; delete branch (FRG-PROC-007)
