# IMP — Import & Filename Parsing Specification

## Purpose

Baseline requirements for import & filename parsing, mined from the
Phase 1 reference research (`docs/research/`). Baseline depth per the Phase 2 scope
decision: SHALL + coarse acceptance; scenario-level elaboration happens in the
milestone change that implements each requirement (FRG-PROC-003, FRG-PROC-009).

## Requirements

### Requirement: FRG-IMP-001 — Single parser implementation for all consumers

The system SHALL provide exactly one comic-name parsing implementation, and all consumers — library scanning, post-processing/import, indexer release-title evaluation, and series/download folder-name parsing (via an explicit mode flag) — SHALL invoke that single implementation with no per-consumer re-implementations of parsing or issue normalization.

- **Milestone**: M1
- **Source**: MFP §4 item 18 (four divergent re-implementations in Mylar); MFP §5 "single implementation used for parsing, matching, and renaming"; SA §2.5 (pure-function title parser shared shape).
- **Notes**: Directly reverses Mylar's helpers/PostProcessor/filers/importer divergence. Folder parsing reuses the engine with a mode flag (MFP §5 last bullet); which field came from filename vs folder is reported by PP evidence aggregation (see PP), not by forked parsers.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A code-level audit (import-graph test) shows one parser module; folder-name and release-title parsing tests exercise the same entry point as filename tests; no duplicate issue-normalization logic exists outside it.

### Requirement: FRG-IMP-002 — Pure, deterministic parse function

The parser SHALL be a pure function of its inputs (filename, optional relative directory, explicit options including the current-year cutoff), with no dependence on global configuration, watchlists, database state, or the system clock, such that identical inputs always yield identical output.

- **Milestone**: M1
- **Source**: MFP §4 item 16 (config/state coupling, watch-mode vs justparse divergence); MFP §5 Tokenization & normalization, first bullet.
- **Notes**: The future-year rejection cutoff (see year extraction below) must be a parameter, not `datetime.now()`, so the 2099-style corpus rows never rot. Mylar's mode-dependent results (matchIT vs justparse) are a deliberate divergence: one mode-independent result shape.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Property test: repeated calls with identical inputs (including a pinned reference-year parameter) are byte-identical; the parser module imports no config/DB/clock modules.

### Requirement: FRG-IMP-003 — Structured parse result with confidence, no sentinels, no crashes

Every parse SHALL return a structured result under a single status vocabulary — success with all fields typed and optional fields explicitly null, or failure with a machine-readable reason and any partial fields — including a confidence signal and an optional token-classification trace, and SHALL never raise an unhandled exception or emit sentinel strings (no `XCV`/`c11`-style placeholders, no `999999999999999` magic values) for any input.

- **Milestone**: M1
- **Source**: MFP §4 items 10, 17 (sentinel scheme, silent failure, dual status keys, no confidence); MFP §5 Quality/diagnostics; SA §2.5 (mapping failures become rejection reasons, never exceptions).
- **Notes**: Replaces Mylar's `parse_status`/`process_status` split and bare-except wrapping. Confidence feeds release-decision and import-decision engines (PP) and the interactive UI.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Fuzz/property tests over arbitrary Unicode filenames (plus the full corpus) produce a valid result object on every input with zero unhandled exceptions; schema validation rejects sentinel values; failure results carry a reason enum.

### Requirement: FRG-IMP-004 — Tokenization and separator handling

The parser SHALL treat spaces, underscores, and commas as token separators, SHALL additionally treat dots as separators when dots are the dominant separator (NZB-style names), and SHALL preserve parenthesized `(...)` and bracketed `[...]` groups as atomic annotation tokens.

- **Milestone**: M1
- **Source**: MFP §1 step 7, §2.1; MFP §5 Tokenization bullet 2; MFP §4 items 1, 3 (literal `\s` bug, first-occurrence `list.index` fragility to avoid).
- **Notes**: Token positions must be tracked by index-stable means (not value lookup) so repeated tokens (`Batman 66 66 (2016)`) cannot corrupt boundaries (MFP §4 item 3). Title-boundary determination is grammar/priority over the token stream (MFP §5 Series title bullet 2).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Corpus rows for space-, underscore-, comma-, and dot-separated forms (e.g. rows 11, 62, 69, 70) parse to identical structured results as their space-separated equivalents.

### Requirement: FRG-IMP-005 — Unicode-native handling and single-sourced normalization

The parser SHALL handle Unicode natively — NFC/NFKD-aware comparison, em/en/two-em dashes, curly quotes, fraction glyphs, `∞` — without sentinel substitution, and the normalized matching key (the dynamic-name analogue: punctuation folding, article handling, case/separator collapsing) SHALL be produced by exactly one normalization function shared by parsing, series matching, and renaming.

- **Milestone**: M1
- **Source**: MFP §2.13, §4 item 10; MFP §5 Tokenization bullet 3; SA §2.5 (clean-title mapping).
- **Notes**: `series_name` (raw, minus consumed designators) and the folded matching key are both returned (MFP output dict: `series_name` / `series_name_decoded` / `dynamic_name`).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Titles containing arbitrary ASCII substrings (`c11`, `XCV`) and Unicode punctuation round-trip unmangled (corpus rows 16, 17, 67 plus adversarial cases); one normalization function is referenced by parser, matcher, and renamer tests.

### Requirement: FRG-IMP-006 — Archive extension recognition

The parser and library walker SHALL recognize comic file extensions case-insensitively (`cbz`, `cbr`, `cb7`, `cbt`, `pdf` at minimum) and SHALL strip exactly the single trailing extension, never other occurrences of the extension substring within the name.

- **Milestone**: M1
- **Source**: MFP §2.1; MFP §4 item 2 (case-sensitivity + unescaped `re.sub` bugs).
- **Notes**: Extension list defined once (Mylar hardcodes it twice). `.cbt` is an addition over Mylar; epub deliberately out (no reader in scope).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** `Batman 404 (1987).CBZ` (corpus row 68) parses identically to the lowercase form with `type = cbz`; a filename containing the extension substring mid-name (e.g. `acbr`) is not mangled.

### Requirement: FRG-IMP-007 — Plain integer and #-prefixed issue numbers with leading-title guard

The parser SHALL recognize plain integer issue numbers with arbitrary zero-padding and `#`-prefixed issue numbers (the `#` token taking precedence as the issue anchor), and SHALL not classify a numeric token as the issue number when it begins the series title.

- **Milestone**: M1
- **Source**: MFP §2.2; MFP §5 Issue numbers bullets 1–2; MFP §4 item 12 (first-`#` assumption to avoid — the matched token's own `#`, not the first `#` in the name, governs).
- **Notes**: Selection among multiple candidates (right-most, hyphen-trailing, `(of N)` override, year-position exclusion, dash-number demotion — MFP §2.2 last bullet) is pinned by corpus rows 31, 32, 64, 65 rather than spelled as separate requirements.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Corpus rows 1–5 (Batman 404 forms, 100 Bullets, 52) and row 6/7-family leading-number titles produce the expected series/issue split; `#`-anchored row 2 pins precedence.

### Requirement: FRG-IMP-008 — Decimal, negative, and Unicode-fraction issue numbers

The parser SHALL recognize decimal issues (`15.5`, `.5`, `000.0000½` composites), negative issues (`-1`), and Unicode fraction/infinity issue glyphs (`½ ¼ ¾ ∞`), normalizing each to a canonical numeric-plus-display form in the structured output.

- **Milestone**: M1
- **Source**: MFP §2.2 (decimals, negatives), §2.4 (fractions, infinity); MFP §4 item 11 (`infinity` token hazard); MFP §5 Issue numbers bullet 1.
- **Notes**: Canonical form is a structured (value, suffix, display) record, not a rewritten string — divergence from Mylar's sentinel/re-join pipeline.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Corpus rows 12–17 parse to the expected canonical issue values (½ → 0.5 with original glyph retained for display), and `Infinity`-titled series (row 67 guard) never become `float('inf')` issues.

### Requirement: FRG-IMP-009 — Alphanumeric issue suffixes and named issues

The parser SHALL recognize issue numbers with alphanumeric suffixes from a configurable exception vocabulary (at minimum AU, AI, INH, NOW, BEY, MU, HU, LR, DEATHS, ALPHA, OMEGA, seasonal names, Director's Cut) in glued (`15A`, `027AU`), space-separated (`10 AI`), and dotted (`008.NOW`, incl. trailing `!`) forms, requiring a `#` anchor for pure-alpha issue names, while guarding single-letter suffixes against cover-variant and mid-title false positives.

- **Milestone**: M1
- **Source**: MFP §2.3; MFP §4 item 5 (single-letter false positives); MFP §5 Issue numbers bullet 1.
- **Notes**: The vocabulary is data (configurable/extensible), not code. Suffix is a structured field on the issue number; PostProcessor-style canonical remapping tables collapse into the single implementation (see ordering-key requirement).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Corpus rows 18–30 (incl. `Cover B` row 25 and `Black and White` row 29 as adversarial guards, `#Alpha` row 28) all parse as tabled.

### Requirement: FRG-IMP-010 — Issue ranges

The parser SHALL handle issue-range tokens (`01-02`, `112/113`, `01-66`) either by representing the range explicitly in the structured output or by returning a distinct range-detected diagnostic failure — never via hardcoded per-title literals and never by silently picking one endpoint.

- **Milestone**: M1
- **Source**: MFP §2.2 (ranges), §4 item 13 (hardcoded literals in `issuedigits`); MFP §5 Issue numbers bullet 4.
- **Notes**: M1 may satisfy this via the diagnostic-rejection arm; full range modeling (packs) can be widened later without changing the requirement. Feeds pack handling in search/DDL.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Corpus row 74 (`Preacher 01-66 Complete`) and `112/113`-style names yield either a structured range or the range diagnostic; no hardcoded range literals exist in the codebase.

### Requirement: FRG-IMP-011 — Mini-series counts and cover/page-tag stripping

The parser SHALL use mini-series count markers (`(of 12)`, `01 of 8`, decimal totals like `(of 7.3)`) to anchor the true issue number, and SHALL consume cover-count (`2 covers`) and page/quality tags (`36p ctc`, `1440px`) without ever classifying them as issue numbers, exposing the mini-series total as a structured field.

- **Milestone**: M1
- **Source**: MFP §2.5; MFP §5 Issue numbers bullet 3.
- **Notes**: `(of infinity)` exclusion (MFP §2.5) carried over as an adversarial corpus case.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Corpus rows 31–36 parse as tabled, with `(of N)` overriding competing numeric candidates (row 32) and the total surfaced in output.

### Requirement: FRG-IMP-012 — Volume designators including volume-years

The parser SHALL recognize volume designators in the forms `v2`/`V2`/`v02`, `vol 2`, `vol.2`, `vol. 2`, `volume 2`, glued `volume2`, roman-numeral (`Vol III` → 3), volume-year (`v2013`), and year-range (`(1953-)`, `(1953-1959)`) forms, distinguishing ordinal volumes from volume-years as distinct structured fields, and SHALL not classify `Part N` as a volume.

- **Milestone**: M1
- **Source**: MFP §2.6, §4 items 6–7; MFP §5 Volumes.
- **Notes**: Deliberate divergences from Mylar: roman numerals captured, `Part` treated as an issue/chapter cue instead of a volume, output is structured (ordinal vs year) rather than a re-prefixed `vN` string that downstream code re-guesses by digit count (search_filer.py:533-580 behavior becomes a typed field). Default-`v1` fabrication only where a trade format demands it (see booktype).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Corpus rows 37–44 parse as tabled, with row 43 yielding volume 3 (fixing Mylar's roman-numeral discard) and row 42 yielding no volume (Part ≠ volume divergence).

### Requirement: FRG-IMP-013 — Year and cover-date extraction

The parser SHALL extract the cover year from `(1987)`, bare-year, `YYYY-MM`, `YYYY-MM-DD`, and month-name (`(June 2019)`) forms, preferring the right-most plausible date, excluding years positioned inside the series-title region, treating years more than one year beyond the supplied reference year as title content, and supporting at least 1900–2099 with no hardcoded upper bounds.

- **Milestone**: M1
- **Source**: MFP §2.7, §4 items 8–9 (`'19'/'20'` window hack, `1970<year<2020` hardcode, `%Y%m` false-positive); MFP §5 Dates & years.
- **Notes**: Six-digit tokens must not validate as `%Y%m` dates when they are plausible issue numbers (MFP §4 item 9 regression). Future-year cutoff comes from the purity requirement's reference-year parameter.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Corpus rows 1, 7 (`Spider-Man 2099` stays a title word), 10, and month-name date cases parse as tabled with a pinned reference-year parameter; an 18xx reprint year test passes.

### Requirement: FRG-IMP-014 — Year-equals-issue one-shot disambiguation

When the only issue-number candidate equals the detected cover year (e.g. `Title 2023 (2023)`), the parser SHALL classify the number as title content and the work as a one-shot/trade-style book (or as a year-issued annual when annual markers are present) rather than emitting issue #2023.

- **Milestone**: M1
- **Source**: MFP §2.7 (`issue2year`), §2.9 (2024-01-07 one-shot rule); MFP §5 Dates & years bullet 2.
- **Notes**: Interacts with annual classification and booktype below; the corpus pins the precedence (annual marker beats one-shot reclassification).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Corpus rows 52 (one-shot, number folded into title) and 55 (`Batman Annual 2021 (2021)` → issue 2021, annual classification) both parse as tabled.

### Requirement: FRG-IMP-015 — Annuals and specials as structured classification

The parser SHALL detect `Annual`, `BiAnnual`, and `Special` markers (including combined `1997 Annual` year forms) and expose them as a structured issue-classification field with the issue number kept numeric, removing the marker from the series title — never by rewriting the issue number to strings like `Annual 02`.

- **Milestone**: M1
- **Source**: MFP §2.8; MFP §5 Annuals, specials & book types bullet 1.
- **Notes**: Deliberate divergence: Mylar's `Annual <n>` string rewrites (and `ANNUALS_ON` config-gating of parse output) are replaced by a typed field; rendering `Annual` into filenames is the renamer's job (PP), preserving the round-trip contract of MFP §2.16. Season words (`Summer Special`, row 58) are pinned by corpus rather than modeled deeply.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Corpus rows 53–58, 62, 71 parse with classification ∈ {annual, biannual, special}, numeric issue (or year-as-issue per row 54/55), and marker-free series titles.

### Requirement: FRG-IMP-016 — Booktype detection as distinct enum

The parser SHALL classify book type from filename cues into distinct enum values — issue (default), TPB (`TPB`, `digital TPB`, `trade paperback`), GN (`GN`, `graphic novel`), HC (`HC`, `hardcover`), one-shot — with multi-word forms matched across tokens, trade formats interpreting the trailing number as the volume (defaulting to volume 1 only for explicit trade formats), and no ambiguous `TPB/GN/HC/One-Shot` union value.

- **Milestone**: M1
- **Source**: MFP §2.9, §4 item 14; MFP §5 Annuals, specials & book types bullet 2; MFS §3 (booktype match in result evaluation depends on this).
- **Notes**: Filename booktype is a hint; authoritative booktype comes from ComicVine metadata (MFP §2.9 last bullet — META area). The enum must be shared with the search-result evaluation layer.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Corpus rows 45–52 parse as tabled, including row 50 (`Graphic Novel` two-word form, dead code in Mylar) and row 46 (TPB with volume).

### Requirement: FRG-IMP-017 — Generic annotation classification (scan groups, edition tags)

The parser SHALL classify trailing parenthesized/bracketed annotation groups generically — extracting release/scanner group tags as a structured `scan_group` field (any trailing annotation that is not a date, count, or recognized edition tag) and recognizing edition/quality annotations (`Digital`, `Webrip`, `c2c`, `Deluxe Edition`, `[1920px]`-style bracket tags) as annotations excluded from title, issue, and volume — with no hardcoded group list required for correctness.

- **Milestone**: M1
- **Source**: MFP §2.10, §2.11, §4 items 4, 15, 19; MFP §5 Tags, groups & pass-through metadata bullets 1–2.
- **Notes**: Kills Mylar's five-substring ripper list and the Glorith-HD bespoke hacks (the Glorith corpus row 62 must pass via the generic rules). A small known-group list may exist only for disambiguation/scoring, never for correctness. Scan group feeds release-group scoring (quality/decision area) and the `{Release Group}` rename token (PP).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Corpus rows 59–62 yield the tabled scan groups without any built-in group list; `(Oroboros)`-style unknown groups are captured; edition tags in rows 35, 46, 51, 59 never leak into title/issue/volume.

### Requirement: FRG-IMP-018 — Embedded issue-ID pass-through

The parser SHALL extract an embedded issue identifier in the `[__<id>__]` convention anywhere in the name, returning it as a structured field and removing it from all other parsed fields.

- **Milestone**: M1
- **Source**: MFP §2.15; MFS §4 (DDL queue hands completed downloads to PP with `[__issueid__]` tags); MFP §5 pass-through metadata bullet 3.
- **Notes**: M1-critical because the built-in DDL path (in the vertical slice) uses this tag as its snatch↔completion handshake. Renamer (PP) may embed it to make files self-identifying.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Corpus row 66 parses with `issue_id = 123456` and an otherwise-normal result; a DDL-style tagged filename round-trips through PP matching on the ID.

### Requirement: FRG-IMP-019 — Series title output and alternate title splits

The parser SHALL return the series title exactly as present in the name minus consumed designators, plus the normalization-folded matching variant, plus any alternate series/issue-title split implied by hyphen-delimited titles (`Series - Subtitle NN (Year)`, trailing `- Issue Title` forms), without corrupting titles whose words themselves contain hyphens.

- **Milestone**: M1
- **Source**: MFP §2.15 (alt_series/alt_issue), §4 item 20; MFP §5 Series title & matching support.
- **Notes**: Alternate splits are hints for series matching (search/metadata areas), carried as structured optional fields, not extra parse modes.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Corpus rows 9 (`X-23`), 64 (`Batman - The Long Halloween` with alt split), 65 (`Daredevil 600 - Mayor Fisk`), and 72 (mid-title roman numeral) parse as tabled.

### Requirement: FRG-IMP-020 — Total, collision-free issue ordering keys

The system SHALL provide a single issue-number ordering/comparison implementation producing a total order that is collision-free across the supported issue vocabulary (integers, decimals, negatives, fractions, alpha suffixes, annual classification), used by parsing, matching, sorting, and renaming alike, with no magnitude-domain mixing or unparseable-sentinel values.

- **Milestone**: M1
- **Source**: MFP §2.3 (ord-sum scoring), §4 item 13 (collisions, `*1000` vs ord sums vs sentinels); MFP §5 Issue numbers bullet 5.
- **Notes**: Replaces `helpers.issuedigits`. Recommend a sort-key tuple (class, numeric, suffix rank) rather than a single scalar — design freedom, but the collision-free property is the requirement.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A pairwise-ordering property test over the corpus issue values (plus generated suffix combinations) shows antisymmetry, transitivity, and zero collisions between distinct issues; exactly one comparator implementation exists.

### Requirement: FRG-IMP-021 — Corpus-driven regression suite

The parser SHALL be covered by a table-driven regression corpus seeded with the full 67-row corpus plus the 8 supplementary edge rows from the research report, grown over time such that every behavioral rule in this AREA has at least one positive and one adversarial corpus case, and every parser bug fix adds its reproducing row before the fix lands.

- **Milestone**: M1
- **Source**: MFP §3 (corpus rows 1–75); MFP §5 Quality, diagnostics & testing bullet 2; CLAUDE.md FRG-PROC-004 (tests traceable).
- **Notes**: "Full corpus strength IS M1" per milestone definition. Rows the research flags as fuzzy (25, 58) are pinned to the *desired* column, i.e. we assert the corrected behavior, not Mylar's. Each corpus row should be taggable to the requirement it evidences so the traceability matrix (FRG-PROC-005) can be generated.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** CI runs the corpus table verbatim (all 75 seed rows asserting series, issue, volume, year, booktype, classification, scan group as tabled) and fails on any regression; the corpus file is additive-only.

### Requirement: FRG-IMP-022 — Library scan walk

The library scanner SHALL recursively enumerate comic files under configured root/series paths, recognizing extensions case-insensitively and skipping junk (AppleDouble/`@eaDir` dirs, `._` resource forks, dotfiles, zero-byte files, unpack-temp folders), and SHALL reconcile the database against disk by removing file records whose files have vanished before evaluating unmapped files.

- **Milestone**: M2
- **Source**: MFP §2.1 (directory walk skips); SA §5.5 (DiskScanService, MediaFileTableCleanupService); MFS capability map IMP (recursive library scan).
- **Notes**: Per-series rescan is the same walk scoped to one series path (`forceRescan` analogue, MFS §8). Unmapped files feed the shared import pipeline (see PP shared-pipeline requirement) — the scanner itself makes no import decisions.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A fixture tree containing junk artifacts and an uppercase-extension file scans to exactly the expected file set; deleting a file on disk and rescanning removes its DB record.

### Requirement: FRG-IMP-023 — Existing-library import staging and review

The system SHALL stage library-scan parse results grouped by normalized series name into a reviewable import queue, presenting per-group would-be matches with parse confidence, and SHALL support mass import, per-group selection/override, and re-check before committing files to the library.

- **Milestone**: M2
- **Source**: MFS §4 Library import (librarysync staging, import UI); SA §5.5 (manual import as the override escape hatch); MFP §5 (structured output powers the review UI).
- **Notes**: ComicVine identification search for unmatched groups belongs to the metadata AREA; this requirement covers staging/review mechanics. Optional move/rename-on-import reuses the PP renaming engine (IMP_MOVE/IMP_RENAME analogue) — no second file-ops path.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Importing a fixture library of ≥3 series (with one ambiguous group) via the review UI creates the correct series/issue/file records, with the ambiguous group resolved only after user override.

### Requirement: FRG-IMP-024 — Embedded metadata read during import

During library import, the system SHALL read embedded ComicInfo.xml metadata (and embedded ComicVine issue IDs) from archives where present and SHALL prefer a verified embedded ID over filename-parse results when matching files to series/issues.

- **Milestone**: M2
- **Source**: MFS §4 Library import (embedded ComicInfo read, direct add-by-ID); MFS capability map IMP.
- **Notes**: Read-side only here; writing tags is PP. Embedded evidence is one more input to the shared evidence-aggregation model (PP) with highest confidence when verified against ComicVine.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A fixture cbz with a ComicInfo.xml carrying a CV issue ID imports directly to the right issue even under a misleading filename; a conflicting-ID case surfaces as a review item rather than a silent trust.

### Requirement: FRG-IMP-025 — Story-arc reading-order prefix

The parser SHALL recognize a leading reading-order prefix (`NNN-`, ≤3 digits before the first hyphen) when parsing in arc context, returning the sequence number as a structured field and excluding it from the series title.

- **Milestone**: B
- **Source**: MFP §2.14, §3 row 63; MFP §5 pass-through metadata bullet 3.
- **Notes**: Backlogged with story arcs (ARC area) generally; kept in the baseline so the corpus row has an owner and the token grammar reserves the prefix rule.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Corpus row 63 parses with `reading_order = 023` and an otherwise-normal result; non-arc mode leaves the same name's title untouched.

