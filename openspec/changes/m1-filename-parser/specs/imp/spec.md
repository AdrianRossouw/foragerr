## MODIFIED Requirements

### Requirement: FRG-IMP-001 — Single parser implementation for all consumers

The system SHALL provide exactly one comic-name parsing implementation, and all consumers — library scanning, post-processing/import, indexer release-title evaluation, and series/download folder-name parsing (via an explicit mode flag) — SHALL invoke that single implementation with no per-consumer re-implementations of parsing or issue normalization.

- **Milestone**: M1
- **Source**: MFP §4 item 18 (four divergent re-implementations in Mylar); MFP §5 "single implementation used for parsing, matching, and renaming"; SA §2.5 (pure-function title parser shared shape).
- **Notes**: Directly reverses Mylar's helpers/PostProcessor/filers/importer divergence. Folder parsing reuses the engine with a mode flag (MFP §5 last bullet); which field came from filename vs folder is reported by PP evidence aggregation (see PP), not by forked parsers.

#### Scenario: Filename and release title parse through the same entry point

- **WHEN** the filename `Invincible Iron Man 019 (2016) (Digital) (Minutemen-Faessla).cbz` and the extensionless indexer release title `Invincible Iron Man 019 (2016) (Digital) (Minutemen-Faessla)` are each passed to `parse(name, reference_year=2026)`
- **THEN** both calls resolve to the same function object in the same module, and the two results are field-for-field identical (`series_name = "Invincible Iron Man"`, issue value 19, year 2016, `scan_group = "Minutemen-Faessla"`) except for the extension-derived `type` field, which is `cbz` for the filename and None for the release title

#### Scenario: Folder-name parsing reuses the engine via a mode flag

- **WHEN** the series folder name `Batman (2016)` is parsed with the folder-mode flag set on the same `parse` entry point used for filenames
- **THEN** the result comes from the same parser module (no separate folder-parser code path exists), with `series_name = "Batman"`, year 2016, and issue None — and the folder-mode flag changes only mode-appropriate expectations (no extension, no issue required), not the result shape

#### Scenario: Import-graph audit finds no duplicate parsing or normalization logic

- **WHEN** an automated import-graph/test-level audit enumerates modules that implement filename tokenization, issue-number recognition, or issue normalization
- **THEN** exactly one parser module is found; library-scan tests, post-processing tests, release-title-evaluation tests, and folder-name tests all import their parse entry point from that module; and no second implementation of issue normalization exists anywhere in the codebase

### Requirement: FRG-IMP-002 — Pure, deterministic parse function

The parser SHALL be a pure function of its inputs (filename, optional relative directory, explicit options including the current-year cutoff), with no dependence on global configuration, watchlists, database state, or the system clock, such that identical inputs always yield identical output.

- **Milestone**: M1
- **Source**: MFP §4 item 16 (config/state coupling, watch-mode vs justparse divergence); MFP §5 Tokenization & normalization, first bullet.
- **Notes**: The future-year rejection cutoff (see year extraction below) must be a parameter, not `datetime.now()`, so the 2099-style corpus rows never rot. Mylar's mode-dependent results (matchIT vs justparse) are a deliberate divergence: one mode-independent result shape.

#### Scenario: Identical inputs yield byte-identical results

- **WHEN** `parse("Spider-Man 2099 001 (1992).cbz", reference_year=2026)` is invoked repeatedly — including across separate processes and with shuffled call order relative to other parses
- **THEN** every invocation returns a structurally and byte-identical serialized result (`series_name = "Spider-Man 2099"`, issue value 1 with display `001`, year 1992), with no variation from call count, ordering, or ambient state

#### Scenario: Future-year behavior is governed solely by the reference-year parameter

- **WHEN** `Spider-Man 2099 001 (1992).cbz` is parsed once with `reference_year=2026` and once with `reference_year=2100`, on a machine whose system clock is set to an arbitrary date
- **THEN** the two results differ only as a consequence of the explicit parameter (with `reference_year=2026`, 2099 is implausibly future and remains title content; the year is 1992 in both), and a static check confirms the parser module imports no clock, config, watchlist, or database modules

#### Scenario: Global state changes cannot alter parse output

- **WHEN** `parse("Batman Annual 02 (2017).cbz", reference_year=2026)` is called before and after mutating application configuration, database contents, and environment variables
- **THEN** the two results are identical — annual classification and all other fields are computed from the name and the explicit options alone, with no analogue of Mylar's `ANNUALS_ON`/watch-mode output divergence

### Requirement: FRG-IMP-003 — Structured parse result with confidence, no sentinels, no crashes

Every parse SHALL return a structured result under a single status vocabulary — success with all fields typed and optional fields explicitly null, or failure with a machine-readable reason and any partial fields — including a confidence signal and an optional token-classification trace, and SHALL never raise an unhandled exception or emit sentinel strings (no `XCV`/`c11`-style placeholders, no `999999999999999` magic values) for any input.

- **Milestone**: M1
- **Source**: MFP §4 items 10, 17 (sentinel scheme, silent failure, dual status keys, no confidence); MFP §5 Quality/diagnostics; SA §2.5 (mapping failures become rejection reasons, never exceptions).
- **Notes**: Replaces Mylar's `parse_status`/`process_status` split and bare-except wrapping. Confidence feeds release-decision and import-decision engines (PP) and the interactive UI.

#### Scenario: Absent fields are None, never sentinel values

- **WHEN** `Batman 404.cbz` (corpus row 3, no year present) is parsed
- **THEN** the result reports success with `series_name = "Batman"`, issue value 404, and the year, volume, volume-year, scan-group, and issue-id fields all explicitly None — and schema validation over the entire result rejects any occurrence of `XCV`, `c11`/`f11`/`g11`/`h11`, `999999999999999`, or any other sentinel placeholder

#### Scenario: Unparseable input returns a structured failure, not an exception

- **WHEN** a name with no recoverable series/issue content — e.g. `()()( ).cbz` or the empty string — is parsed
- **THEN** no exception propagates; the result carries the single failure status, a machine-readable reason from the failure-reason enum (e.g. `NO_SERIES_TITLE`), any salvageable partial fields, and a confidence score, under the same result type as successes (no second status vocabulary)

#### Scenario: Zero-crash fuzz bar over arbitrary Unicode

- **WHEN** a fuzz/property suite feeds the parser arbitrary Unicode strings (including control characters, unpaired surrogates, lone brackets, and multi-megabyte names) plus all 75 corpus rows
- **THEN** every single input yields a valid structured result object — success or reasoned failure — with zero unhandled exceptions across the whole sweep

#### Scenario: Confidence signal discriminates anchored from ambiguous parses

- **WHEN** `Batman #404 (1987).cbr` (corpus row 2, `#`-anchored issue and parenthesized year) and an ambiguous name such as `Preacher 01-66 Complete.cbz` (corpus row 74) are parsed
- **THEN** both results carry a numeric confidence score, the anchored parse scores strictly higher than the ambiguous one, and requesting the optional token-classification trace returns a per-token classification for every token in the input

### Requirement: FRG-IMP-004 — Tokenization and separator handling

The parser SHALL treat spaces, underscores, and commas as token separators, SHALL additionally treat dots as separators when dots are the dominant separator (NZB-style names), and SHALL preserve parenthesized `(...)` and bracketed `[...]` groups as atomic annotation tokens.

- **Milestone**: M1
- **Source**: MFP §1 step 7, §2.1; MFP §5 Tokenization bullet 2; MFP §4 items 1, 3 (literal `\s` bug, first-occurrence `list.index` fragility to avoid).
- **Notes**: Token positions must be tracked by index-stable means (not value lookup) so repeated tokens (`Batman 66 66 (2016)`) cannot corrupt boundaries (MFP §4 item 3). Title-boundary determination is grammar/priority over the token stream (MFP §5 Series title bullet 2).

#### Scenario: Underscore- and comma-separated names parse identically to spaces

- **WHEN** `Batman_404_(1987).cbz` (corpus row 69), `Batman,404,(1987).cbz` (corpus row 70), and `Batman 404 (1987).cbz` (corpus row 1) are each parsed
- **THEN** all three yield identical structured results: `series_name = "Batman"`, issue value 404, year 1987 — and the underscore-mangled `Captain_Atom_007__2012___digital-TheGroup_.cbr` parses to `series_name = "Captain Atom"`, issue value 7 with display `007`, year 2012, with `digital` classified as an edition annotation and `TheGroup` as the scan group

#### Scenario: Dots split only when dot-dominant

- **WHEN** the NZB-style name `Amazing.Spider-Man.798.2018.Digital.Empire.cbr` (corpus row 11) and the space-separated `Batman Beyond 2.0 015 (2013).cbz` (corpus row 8) are parsed
- **THEN** the dot-dominant name tokenizes on dots, yielding `series_name = "Amazing Spider-Man"`, issue value 798, year 2018; while in the space-dominant name the dot in `2.0` is not a separator, so `series_name = "Batman Beyond 2.0"` survives intact with issue value 15 and year 2013

#### Scenario: Parenthesized and bracketed groups are atomic tokens

- **WHEN** `Saga 55 (2018) (digital) (36p ctc).cbz` (corpus row 35) is parsed
- **THEN** `(2018)`, `(digital)`, and `(36p ctc)` are each classified as single atomic annotation tokens — none of their inner words leak into the series title or issue candidates — producing `series_name = "Saga"`, issue value 55, year 2018

#### Scenario: Repeated tokens cannot corrupt position bookkeeping

- **WHEN** `Batman 66 66 (2016).cbz` — a title whose word repeats the issue number — is parsed
- **THEN** index-stable position tracking (never first-occurrence value lookup) yields `series_name = "Batman 66"`, issue value 66, year 2016, with the title boundary placed after the first `66` and no token misattribution

### Requirement: FRG-IMP-005 — Unicode-native handling and single-sourced normalization

The parser SHALL handle Unicode natively — NFC/NFKD-aware comparison, em/en/two-em dashes, curly quotes, fraction glyphs, `∞` — without sentinel substitution, and the normalized matching key (the dynamic-name analogue: punctuation folding, article handling, case/separator collapsing) SHALL be produced by exactly one normalization function shared by parsing, series matching, and renaming.

- **Milestone**: M1
- **Source**: MFP §2.13, §4 item 10; MFP §5 Tokenization bullet 3; SA §2.5 (clean-title mapping).
- **Notes**: `series_name` (raw, minus consumed designators) and the folded matching key are both returned (MFP output dict: `series_name` / `series_name_decoded` / `dynamic_name`).

#### Scenario: Titles containing former sentinel substrings round-trip unmangled

- **WHEN** filenames whose titles legitimately contain Mylar's sentinel substrings — e.g. `Project XCV 003 (2020).cbz` and `Apache c11 Squadron 01 (2019).cbz` — are parsed
- **THEN** the series names are returned exactly as `Project XCV` and `Apache c11 Squadron` with no substitution artifacts, because no sentinel-replacement pass exists anywhere in the pipeline

#### Scenario: Unicode dashes and curly quotes are handled without pre-mangling

- **WHEN** `Batman — The Long Halloween 05 (1997).cbz` (em-dash variant of corpus row 64) and `Gideon Falls Director’s Cut 1 (2018).cbz` (curly-apostrophe variant of corpus row 30) are parsed
- **THEN** the em dash is treated as the same title/subtitle delimiter as the ASCII ` - ` form (issue value 5, year 1997, alternate split populated), and the curly apostrophe matches the `Director's Cut` vocabulary entry (issue value 1, edition classified) — with the raw `series_name` preserving the original glyphs

#### Scenario: One normalization function is shared by parser, matcher, and renamer

- **WHEN** `Scott Pilgrim & The Infinite Sadness v3 (2006).cbz` (corpus row 67) is parsed and its folded matching key is compared with the keys produced in series-matching and renaming tests
- **THEN** the raw `series_name` retains the literal `&` (no `f11` sentinel), the folded matching key comes from the single shared normalization function (punctuation folded, articles handled, case/separators collapsed), and an import audit confirms parser, matcher, and renamer all call that one function — no second folding implementation exists

### Requirement: FRG-IMP-006 — Archive extension recognition

The parser and library walker SHALL recognize comic file extensions case-insensitively (`cbz`, `cbr`, `cb7`, `cbt`, `pdf` at minimum) and SHALL strip exactly the single trailing extension, never other occurrences of the extension substring within the name.

- **Milestone**: M1
- **Source**: MFP §2.1; MFP §4 item 2 (case-sensitivity + unescaped `re.sub` bugs).
- **Notes**: Extension list defined once (Mylar hardcodes it twice). `.cbt` is an addition over Mylar; epub deliberately out (no reader in scope).

#### Scenario: Uppercase extensions parse identically to lowercase

- **WHEN** `Batman 404 (1987).CBZ` (corpus row 68) is parsed
- **THEN** the result is field-for-field identical to parsing `Batman 404 (1987).cbz`, with `type = cbz` (normalized lowercase, no dot) — never `unknown`

#### Scenario: Extension substrings inside the name are never stripped

- **WHEN** a filename containing an extension substring mid-name — e.g. `Macbr Chronicles 001 (2015).cbr` and `The cbz Files 002 (2016).cbz` — is parsed
- **THEN** only the single trailing extension is removed; the series names come back as `Macbr Chronicles` and `The cbz Files` with no interior characters deleted or mangled

#### Scenario: Full extension set recognized from a single definition

- **WHEN** `Batman 404 (1987)` is parsed with each of the trailing extensions `.cbz`, `.cbr`, `.cb7`, `.cbt`, `.pdf` (mixed case), and once with `.epub`
- **THEN** the five comic extensions each yield `type` equal to the lowercase extension with otherwise identical results; `.epub` is not recognized as a comic extension; and a code audit shows exactly one extension-list definition shared by the parser and the library walker

### Requirement: FRG-IMP-007 — Plain integer and #-prefixed issue numbers with leading-title guard

The parser SHALL recognize plain integer issue numbers with arbitrary zero-padding and `#`-prefixed issue numbers (the `#` token taking precedence as the issue anchor), and SHALL not classify a numeric token as the issue number when it begins the series title.

- **Milestone**: M1
- **Source**: MFP §2.2; MFP §5 Issue numbers bullets 1–2; MFP §4 item 12 (first-`#` assumption to avoid — the matched token's own `#`, not the first `#` in the name, governs).
- **Notes**: Selection among multiple candidates (right-most, hyphen-trailing, `(of N)` override, year-position exclusion, dash-number demotion — MFP §2.2 last bullet) is pinned by corpus rows 31, 32, 64, 65 rather than spelled as separate requirements.

#### Scenario: Plain and #-anchored integers with padding preserved

- **WHEN** `Batman 404 (1987).cbz` (corpus row 1), `Batman #404 (1987).cbr` (corpus row 2), and `SWAMP THING # 028.cbr` (`#` separated from the digits by a space) are parsed
- **THEN** all three anchor the issue correctly: rows 1–2 yield issue value 404, and the Swamp Thing name yields `series_name = "SWAMP THING"` with issue value 28 and display `028` — the `#` token (including the detached-`#` form) taking precedence as the issue anchor, with zero-padding retained in the display field

#### Scenario: Leading numeric tokens stay in the title

- **WHEN** `100 Bullets 050 (2003).cbz` (corpus row 4), `52 018 (2006).cbz` (corpus row 5), `2000AD prog 2205 (2020).cbz` (corpus row 6), and `4001 A.D. 001 (2016).cbz` (corpus row 75) are parsed with `reference_year=2026`
- **THEN** the leading numbers are classified as title content: `series_name`/issue pairs are `100 Bullets`/50, `52`/18, `2000AD prog`/2205, and `4001 A.D.`/1 — with no special-case title literals in the implementation

#### Scenario: The matched token's own # governs, not the first # in the name

- **WHEN** a name containing two `#` characters where the issue is the later one — e.g. `Beach Blanket Bingo #3 Special #005 (2001).cbz`-style input — is parsed
- **THEN** the issue number is extracted from the `#` token actually selected as the issue anchor (issue value 5), not from the offset of the first `#` in the raw string

#### Scenario: Candidate selection pins — dash demotion and rightmost survivor

- **WHEN** `Daredevil 600 - Mayor Fisk (2018).cbz` (corpus row 65) and `Amazing Mary Jane (2019) 002.cbr` (corpus row 10) are parsed
- **THEN** row 65 selects issue value 600 (numbers appearing after the title/subtitle dash are demoted, `Mayor Fisk` is not consumed as issue content), and row 10 selects issue value 2 even though the year annotation precedes it — the year-position candidate is excluded from issue selection

### Requirement: FRG-IMP-008 — Decimal, negative, and Unicode-fraction issue numbers

The parser SHALL recognize decimal issues (`15.5`, `.5`, `000.0000½` composites), negative issues (`-1`), and Unicode fraction/infinity issue glyphs (`½ ¼ ¾ ∞`), normalizing each to a canonical numeric-plus-display form in the structured output.

- **Milestone**: M1
- **Source**: MFP §2.2 (decimals, negatives), §2.4 (fractions, infinity); MFP §4 item 11 (`infinity` token hazard); MFP §5 Issue numbers bullet 1.
- **Notes**: Canonical form is a structured (value, suffix, display) record, not a rewritten string — divergence from Mylar's sentinel/re-join pipeline.

#### Scenario: Decimal issues normalize to value-plus-display records

- **WHEN** `Invincible 015.5 (2005).cbz` (corpus row 12), `Elephantmen 20.5 (2009).cbz` (corpus row 13), and `Gold Digger 0.5 (1997).cbr` (corpus row 14) are parsed
- **THEN** the issue records carry numeric values 15.5, 20.5, and 0.5 respectively with the original zero-padded displays (`015.5`, `20.5`, `0.5`) preserved — a structured (value, suffix, display) record, not a rewritten string

#### Scenario: Negative issue numbers

- **WHEN** `Deadpool -1 (1997).cbz` (corpus row 15) is parsed
- **THEN** the issue record has numeric value -1 with display `-1`, `series_name = "Deadpool"`, year 1997 — the sign is part of the typed value, never a magnitude hack

#### Scenario: Unicode fraction glyphs, standalone and composite

- **WHEN** `Uncanny X-Men ½ (1999).cbz` (corpus row 16) and `Batman 000.0000½ (2015).cbz` (corpus row 17) are parsed
- **THEN** row 16 yields issue value 0.5 with the original glyph `½` retained in the display field, and row 17's composite re-joins to value 0.5 with display `000.0000½` — both handled natively with no `XCV`-style sentinel pass

#### Scenario: Infinity words in titles never become infinite issues

- **WHEN** `Scott Pilgrim & The Infinite Sadness v3 (2006).cbz` (corpus row 67) and a late-position case such as `Avengers Infinity 2021 001 (2021).cbz` are parsed
- **THEN** neither `Infinite` nor `Infinity` is parsed as `float('inf')` regardless of token position — the words stay in the series title, and only the literal `∞` glyph produces an infinity-classified issue record

### Requirement: FRG-IMP-009 — Alphanumeric issue suffixes and named issues

The parser SHALL recognize issue numbers with alphanumeric suffixes from a configurable exception vocabulary (at minimum AU, AI, INH, NOW, BEY, MU, HU, LR, DEATHS, ALPHA, OMEGA, seasonal names, Director's Cut) in glued (`15A`, `027AU`), space-separated (`10 AI`), and dotted (`008.NOW`, incl. trailing `!`) forms, requiring a `#` anchor for pure-alpha issue names, while guarding single-letter suffixes against cover-variant and mid-title false positives.

- **Milestone**: M1
- **Source**: MFP §2.3; MFP §4 item 5 (single-letter false positives); MFP §5 Issue numbers bullet 1.
- **Notes**: The vocabulary is data (configurable/extensible), not code. Suffix is a structured field on the issue number; PostProcessor-style canonical remapping tables collapse into the single implementation (see ordering-key requirement).

#### Scenario: Glued, space-separated, and dotted suffix forms

- **WHEN** `Wolverine 027AU (2013).cbz` (corpus row 18), `Age of Ultron 10 AI (2013).cbz` (corpus row 19), `Uncanny Avengers 008.NOW (2013).cbz` (corpus row 20), and `Avengers 024.NOW! (2014).cbz` (corpus row 23) are parsed
- **THEN** each issue record carries the numeric value plus a structured suffix field: (27, `AU`), (10, `AI`), (8, `NOW`), and (24, `NOW`) with the trailing `!` stripped — the suffix is a typed field, never re-joined into a rewritten issue string

#### Scenario: Pure-alpha issue names require a # anchor

- **WHEN** `Secret Wars #Alpha (2015).cbz` (corpus row 28) and the unanchored variant `Secret Wars Alpha (2015).cbz` are parsed
- **THEN** the `#`-anchored form yields the named issue `Alpha` with `series_name = "Secret Wars"`, while the unanchored form keeps `Alpha` in the series title (`Secret Wars Alpha`) with no issue number claimed

#### Scenario: Single-letter and vocabulary-word guards against false positives

- **WHEN** `Justice League 30 Cover B (2019).cbz` (corpus row 25), `Batman Black and White 03 (2013).cbz` (corpus row 29), and `Amazing Spider-Man 015A (2014).cbz` (corpus row 24) are parsed
- **THEN** row 25 yields issue value 30 with `Cover B` classified as a cover-variant annotation (never issue `30 B`); row 29 yields issue value 3 with `Black` and `White` untouched mid-title; and the glued row 24 correctly yields (15, `A`) — single-letter suffixes fire only in the glued-to-digits position

#### Scenario: Suffix vocabulary is configurable data

- **WHEN** `Gideon Falls Director's Cut 1 (2018).cbz` (corpus row 30) is parsed with the default vocabulary, and a hypothetical name `Series 05 XYZ (2020).cbz` is parsed before and after adding `XYZ` to the vocabulary via options
- **THEN** row 30 yields issue value 1 with `Director's Cut` captured as a structured designator (not folded into the issue string); `XYZ` is title content under the default vocabulary but becomes a structured suffix (5, `XYZ`) after the data-only vocabulary extension — with no code change required

### Requirement: FRG-IMP-010 — Issue ranges

The parser SHALL handle issue-range tokens (`01-02`, `112/113`, `01-66`) either by representing the range explicitly in the structured output or by returning a distinct range-detected diagnostic failure — never via hardcoded per-title literals and never by silently picking one endpoint.

- **Milestone**: M1
- **Source**: MFP §2.2 (ranges), §4 item 13 (hardcoded literals in `issuedigits`); MFP §5 Issue numbers bullet 4.
- **Notes**: M1 may satisfy this via the diagnostic-rejection arm; full range modeling (packs) can be widened later without changing the requirement. Feeds pack handling in search/DDL.

#### Scenario: Hyphen range detected, never silently collapsed

- **WHEN** `Preacher 01-66 Complete.cbz` (corpus row 74) is parsed
- **THEN** the result either carries an explicit structured range (start 1, end 66) or is a failure with the distinct range-detected reason enum value — in neither arm does the issue field silently report 1 or 66 alone

#### Scenario: Slash ranges get the same treatment with no hardcoded literals

- **WHEN** `Detective Comics 112/113 (1946).cbz` is parsed, and the codebase is audited for range handling
- **THEN** the slash form produces the same structured-range-or-diagnostic outcome as the hyphen form, and no hardcoded per-title range literals (Mylar's `'112/113'`, `'9-5'`, `'2 & 3'` style tables) exist anywhere in the implementation

#### Scenario: Manga chapter ranges are ranges, not mangled issues

- **WHEN** the manga-style `Berserk v01 c01-05.cbz` (corpus row 73) is parsed
- **THEN** the volume field reports ordinal 1, and the `c01-05` chapter range yields the structured range or the range-detected diagnostic — never a corrupted single issue number

### Requirement: FRG-IMP-011 — Mini-series counts and cover/page-tag stripping

The parser SHALL use mini-series count markers (`(of 12)`, `01 of 8`, decimal totals like `(of 7.3)`) to anchor the true issue number, and SHALL consume cover-count (`2 covers`) and page/quality tags (`36p ctc`, `1440px`) without ever classifying them as issue numbers, exposing the mini-series total as a structured field.

- **Milestone**: M1
- **Source**: MFP §2.5; MFP §5 Issue numbers bullet 3.
- **Notes**: `(of infinity)` exclusion (MFP §2.5) carried over as an adversarial corpus case.

#### Scenario: (of N) anchors the issue over competing numeric candidates

- **WHEN** `Batman 39 (of 52) (2017).cbz` (corpus row 31) and `Kick-Ass 3 01 (of 08) (2013).cbz` (corpus row 32) are parsed
- **THEN** row 31 yields issue value 39 with the mini-series total 52 exposed as a structured field, and row 32 yields `series_name = "Kick-Ass 3"` with issue value 1 and total 8 — the count marker overriding the competing `3` candidate, which stays in the title

#### Scenario: Decimal totals are accepted

- **WHEN** `Empowered 01 (of 7.3) (2015).cbz` (corpus row 33) is parsed
- **THEN** the issue value is 1 and the structured mini-series total is 7.3, with year 2015

#### Scenario: Cover counts and page/quality tags are consumed, never issues

- **WHEN** `Descender 011 (2 covers) (2016).cbz` (corpus row 34), `Saga 55 (2018) (digital) (36p ctc).cbz` (corpus row 35), and `Lazarus 01 (2013) (1440px).cbz` (corpus row 36) are parsed
- **THEN** the issues are 11, 55, and 1 respectively; `2 covers`, `36p ctc`, and `1440px` are classified as annotations and appear in no issue, volume, or title field

#### Scenario: (of infinity) is not a count marker

- **WHEN** an adversarial name `Series 03 (of infinity) (2018).cbz` is parsed
- **THEN** the issue value is 3, the mini-series total field is None, and the `(of infinity)` group is treated as an annotation — no infinite or sentinel total is emitted

### Requirement: FRG-IMP-012 — Volume designators including volume-years

The parser SHALL recognize volume designators in the forms `v2`/`V2`/`v02`, `vol 2`, `vol.2`, `vol. 2`, `volume 2`, glued `volume2`, roman-numeral (`Vol III` → 3), volume-year (`v2013`), and year-range (`(1953-)`, `(1953-1959)`) forms, distinguishing ordinal volumes from volume-years as distinct structured fields, and SHALL not classify `Part N` as a volume.

- **Milestone**: M1
- **Source**: MFP §2.6, §4 items 6–7; MFP §5 Volumes.
- **Notes**: Deliberate divergences from Mylar: roman numerals captured, `Part` treated as an issue/chapter cue instead of a volume, output is structured (ordinal vs year) rather than a re-prefixed `vN` string that downstream code re-guesses by digit count (search_filer.py:533-580 behavior becomes a typed field). Default-`v1` fabrication only where a trade format demands it (see booktype).

#### Scenario: All ordinal volume spellings converge on one typed field

- **WHEN** `Batman v2 015 (2012).cbz` (corpus row 37), `Batman Vol. 2 015 (2012).cbz` (corpus row 38), and `Batman Volume 2 015 (2012).cbz` (corpus row 39) are parsed
- **THEN** all three yield an identical typed ordinal-volume field of 2 (not a re-prefixed `v2` string), with issue value 15, year 2012, and `series_name = "Batman"`

#### Scenario: Roman-numeral volumes are captured, not discarded

- **WHEN** `Sandman Vol III 05 (1991).cbz` (corpus row 43) is parsed
- **THEN** the ordinal volume is 3 (fixing Mylar's silent roman-numeral discard), issue value is 5, year 1991 — while `Star Wars Legacy II 03 (2013).cbz` (corpus row 72), which has no volume keyword, keeps `II` in the title (`series_name = "Star Wars Legacy II"`, issue value 3)

#### Scenario: Volume-years and year-ranges populate the distinct volume-year field

- **WHEN** `Justice League v2017 021 (2018).cbz` (corpus row 40) and `Casper (1953-) 001.cbz` (corpus row 44) are parsed
- **THEN** row 40 reports volume-year 2017 (ordinal volume None) with issue value 21 and cover year 2018, and row 44 reports volume-year 1953 (the trailing-dash range marks a series start year, not a cover date) with issue value 1 and cover year None — ordinal-vs-year being distinct typed fields, never digit-count guessing downstream

#### Scenario: Part N is not a volume

- **WHEN** `Astonishing X-Men Part 2 (2018).cbz` (corpus row 42) is parsed
- **THEN** both volume fields are None — `Part 2` is treated as an issue/chapter cue rather than fabricating volume 2, diverging deliberately from Mylar

### Requirement: FRG-IMP-013 — Year and cover-date extraction

The parser SHALL extract the cover year from `(1987)`, bare-year, `YYYY-MM`, `YYYY-MM-DD`, and month-name (`(June 2019)`) forms, preferring the right-most plausible date, excluding years positioned inside the series-title region, treating years more than one year beyond the supplied reference year as title content, and supporting at least 1900–2099 with no hardcoded upper bounds.

- **Milestone**: M1
- **Source**: MFP §2.7, §4 items 8–9 (`'19'/'20'` window hack, `1970<year<2020` hardcode, `%Y%m` false-positive); MFP §5 Dates & years.
- **Notes**: Six-digit tokens must not validate as `%Y%m` dates when they are plausible issue numbers (MFP §4 item 9 regression). Future-year cutoff comes from the purity requirement's reference-year parameter.

#### Scenario: Standard and left-positioned year forms

- **WHEN** `Batman 404 (1987).cbz` (corpus row 1) and `Amazing Mary Jane (2019) 002.cbr` (corpus row 10) are parsed
- **THEN** row 1 yields year 1987, and row 10 yields year 2019 with issue value 2 — the year annotation is recognized even when it precedes the issue number, and it is never consumed as the issue

#### Scenario: Future years relative to the reference parameter stay in the title

- **WHEN** `Spider-Man 2099 001 (1992).cbz` (corpus row 7) is parsed with `reference_year=2026`
- **THEN** 2099 (more than one year beyond the reference) is classified as title content, giving `series_name = "Spider-Man 2099"`, issue value 1, and year 1992 — and the same input with `reference_year=2100` may treat 2099 as a plausible year, demonstrating the cutoff is the parameter, not a hardcode

#### Scenario: Month-name, ISO, and pre-1900-window forms

- **WHEN** `Saga 55 (June 2019).cbz`, `Amazing Spider-Man 798 2018-05-22.cbz`, and an 18xx reprint such as `Little Nemo 03 (1889).cbz` are parsed
- **THEN** the extracted years are 2019, 2018, and 1889 respectively — month-name groups survive tokenization as date candidates, full ISO dates reduce to their year, and no `'19'/'20'` substring window or `1970<year<2020` hardcode excludes valid dates

#### Scenario: Six-digit tokens that are plausible issues are not %Y%m dates

- **WHEN** `Cerebus 202004 (1995).cbz`-style input containing the six-digit token `202004` alongside a parenthesized year is parsed
- **THEN** `202004` is evaluated as an issue-number candidate, not validated as a `%Y%m` date, and the cover year is 1995

### Requirement: FRG-IMP-014 — Year-equals-issue one-shot disambiguation

When the only issue-number candidate equals the detected cover year (e.g. `Title 2023 (2023)`), the parser SHALL classify the number as title content and the work as a one-shot/trade-style book (or as a year-issued annual when annual markers are present) rather than emitting issue #2023.

- **Milestone**: M1
- **Source**: MFP §2.7 (`issue2year`), §2.9 (2024-01-07 one-shot rule); MFP §5 Dates & years bullet 2.
- **Notes**: Interacts with annual classification and booktype below; the corpus pins the precedence (annual marker beats one-shot reclassification).

#### Scenario: Bare year-equals-issue folds into the title as a one-shot

- **WHEN** `Superman Smashes the Klan 2020 (2020).cbz` (corpus row 52) is parsed
- **THEN** the sole numeric candidate 2020, equalling the cover year, is classified as title content: `series_name = "Superman Smashes the Klan 2020"`, issue None, year 2020, and the booktype enum reports the one-shot/trade-style classification — never issue #2020

#### Scenario: Annual marker beats the one-shot reclassification

- **WHEN** `Batman Annual 2021 (2021).cbz` (corpus row 55) is parsed
- **THEN** the annual marker takes precedence: the issue value is 2021 (year-as-issue), the classification field is `annual`, `series_name = "Batman"`, year 2021, and the booktype stays `issue`

#### Scenario: A distinct issue candidate disables the rule

- **WHEN** `Batman 2020 005 (2020).cbz` — where the year-matching number is not the only candidate — is parsed
- **THEN** the one-shot rule does not fire: the issue value is 5, the year is 2020, and the leading `2020` is resolved by the normal positional rules (title content, giving `series_name = "Batman 2020"`)

### Requirement: FRG-IMP-015 — Annuals and specials as structured classification

The parser SHALL detect `Annual`, `BiAnnual`, and `Special` markers (including combined `1997 Annual` year forms) and expose them as a structured issue-classification field with the issue number kept numeric, removing the marker from the series title — never by rewriting the issue number to strings like `Annual 02`.

- **Milestone**: M1
- **Source**: MFP §2.8; MFP §5 Annuals, specials & book types bullet 1.
- **Notes**: Deliberate divergence: Mylar's `Annual <n>` string rewrites (and `ANNUALS_ON` config-gating of parse output) are replaced by a typed field; rendering `Annual` into filenames is the renamer's job (PP), preserving the round-trip contract of MFP §2.16. Season words (`Summer Special`, row 58) are pinned by corpus rather than modeled deeply.

#### Scenario: Annual with numeric issue stays numeric

- **WHEN** `Batman Annual 02 (2017).cbz` (corpus row 53) and the dot-separated `Batman.Annual.02.2017.digital.Glorith-HD.cbz` (corpus row 62) are parsed
- **THEN** both yield `series_name = "Batman"` (marker removed from the title), issue value 2 with display `02`, year 2017, and classification field `annual` — the issue number is never rewritten to the string `Annual 02`

#### Scenario: Year-annual combined forms

- **WHEN** `Wolverine 1997 Annual.cbz` (corpus row 54) is parsed
- **THEN** the classification is `annual`, the issue value is 1997 (year-as-issue), the year is 1997, and `series_name = "Wolverine"`

#### Scenario: BiAnnual and Special classifications

- **WHEN** `Deadpool BiAnnual 01 (2014).cbz` (corpus row 56), `Gotham City Sirens Special 1 (2022).cbz` (corpus row 57), and `Archie Summer Special 3 (1996).cbz` (corpus row 58) are parsed
- **THEN** the classification fields are `biannual`, `special`, and `special` respectively with numeric issues 1, 1, and 3, marker-free series titles (`Deadpool`, `Gotham City Sirens`, `Archie` — row 58 pinned to the corrected expectation, `Summer` consumed with the special marker), and years 2014, 2022, 1996

#### Scenario: Annual and volume coexist

- **WHEN** `Teen Titans v1 Annual 1 (1967).cbz` (corpus row 71) is parsed
- **THEN** the result simultaneously reports ordinal volume 1, classification `annual`, numeric issue value 1, year 1967, and `series_name = "Teen Titans"` — the annual/volume interplay pinned as independent typed fields

### Requirement: FRG-IMP-016 — Booktype detection as distinct enum

The parser SHALL classify book type from filename cues into distinct enum values — issue (default), TPB (`TPB`, `digital TPB`, `trade paperback`), GN (`GN`, `graphic novel`), HC (`HC`, `hardcover`), one-shot — with multi-word forms matched across tokens, trade formats interpreting the trailing number as the volume (defaulting to volume 1 only for explicit trade formats), and no ambiguous `TPB/GN/HC/One-Shot` union value.

- **Milestone**: M1
- **Source**: MFP §2.9, §4 item 14; MFP §5 Annuals, specials & book types bullet 2; MFS §3 (booktype match in result evaluation depends on this).
- **Notes**: Filename booktype is a hint; authoritative booktype comes from ComicVine metadata (MFP §2.9 last bullet — META area). The enum must be shared with the search-result evaluation layer.

#### Scenario: TPB forms interpret the trailing number as the volume

- **WHEN** `Saga TPB v01 (2013).cbz` (corpus row 45), `Monstress Vol. 06 (2021) (Digital) TPB.cbz` (corpus row 46), and `East of West TPB (2014).cbz` (corpus row 47) are parsed
- **THEN** all three report booktype enum `TPB`; rows 45 and 46 carry ordinal volumes 1 and 6 respectively, and row 47 — an explicit trade with no volume designator — defaults the ordinal volume to 1 (the only case where a v1 is fabricated)

#### Scenario: Multi-word forms match across tokens

- **WHEN** `Pride of Baghdad Graphic Novel (2006).cbz` (corpus row 50) and `Kill or be Killed v1 (2017) (Digital TPB).cbz` (corpus row 51) are parsed
- **THEN** row 50 yields booktype `GN` (fixing Mylar's unreachable two-word match) with `series_name = "Pride of Baghdad"`, and row 51 yields booktype `TPB` from the two-word `Digital TPB` annotation with ordinal volume 1 and year 2017

#### Scenario: HC and GN abbreviations, and no union value exists

- **WHEN** `Watchmen HC (1988).cbz` (corpus row 48) and `Blacksad GN (2010).cbz` (corpus row 49) are parsed, and the booktype enum type is inspected
- **THEN** the booktypes are the distinct enum values `HC` and `GN`, and the enum's member set contains no `TPB/GN/HC/One-Shot`-style union member — one-shot is its own value, assigned by the year-equals-issue rule (corpus row 52), and the same enum type is imported by the search-result evaluation layer

#### Scenario: Default booktype is issue

- **WHEN** `Batman 404 (1987).cbz` (corpus row 1) is parsed
- **THEN** the booktype is the enum value `issue`, with no trade-volume fabrication (volume fields None)

### Requirement: FRG-IMP-017 — Generic annotation classification (scan groups, edition tags)

The parser SHALL classify trailing parenthesized/bracketed annotation groups generically — extracting release/scanner group tags as a structured `scan_group` field (any trailing annotation that is not a date, count, or recognized edition tag) and recognizing edition/quality annotations (`Digital`, `Webrip`, `c2c`, `Deluxe Edition`, `[1920px]`-style bracket tags) as annotations excluded from title, issue, and volume — with no hardcoded group list required for correctness.

- **Milestone**: M1
- **Source**: MFP §2.10, §2.11, §4 items 4, 15, 19; MFP §5 Tags, groups & pass-through metadata bullets 1–2.
- **Notes**: Kills Mylar's five-substring ripper list and the Glorith-HD bespoke hacks (the Glorith corpus row 62 must pass via the generic rules). A small known-group list may exist only for disambiguation/scoring, never for correctness. Scan group feeds release-group scoring (quality/decision area) and the `{Release Group}` rename token (PP).

#### Scenario: Known-style groups extracted by the generic rule, not a list

- **WHEN** `Justice League Dark 016 (2019) (Webrip) (The Last Kryptonian-DCP).cbz` (corpus row 59), `Invincible Iron Man 019 (2016) (Digital) (Minutemen-Faessla).cbz` (corpus row 60), and `Southern Bastards 09 (2015) (digital) (Son of Ultron-Empire).cbr` (corpus row 61) are parsed
- **THEN** the `scan_group` fields are `The Last Kryptonian-DCP`, `Minutemen-Faessla`, and `Son of Ultron-Empire` respectively — produced by the generic trailing-annotation rule (last group that is not a date, count, or edition tag), with a code audit confirming no hardcoded ripper-substring list is consulted for correctness

#### Scenario: Unknown groups are captured too

- **WHEN** `Black Hammer 07 (2017) (Oroboros).cbz` — a group appearing on no known-group list — is parsed
- **THEN** `scan_group = "Oroboros"`, demonstrating the classification is structural, not vocabulary-driven

#### Scenario: Glorith dot-name passes via generic rules, no bespoke hacks

- **WHEN** the dot-separated `Batman.Annual.02.2017.digital.Glorith-HD.cbz` (corpus row 62) is parsed
- **THEN** the generic tokenization and trailing-annotation rules yield `series_name = "Batman"`, classification `annual`, issue value 2, year 2017, edition tag `digital`, and `scan_group = "Glorith-HD"` — with no Glorith-specific code path in the implementation

#### Scenario: Edition and quality tags never leak into title, issue, or volume

- **WHEN** `Saga 55 (2018) (digital) (36p ctc).cbz` (corpus row 35), `Monstress Vol. 06 (2021) (Digital) TPB.cbz` (corpus row 46), and a bracket-tag form such as `Lazarus 01 (2013) [1920px].cbz` are parsed
- **THEN** `digital`, `Digital`, `36p ctc`, and `[1920px]` are all classified as edition/quality annotations, appear in a structured annotations collection, and are absent from `series_name`, the issue record, and both volume fields — and none of them is ever reported as the `scan_group`

### Requirement: FRG-IMP-018 — Embedded issue-ID pass-through

The parser SHALL extract an embedded issue identifier in the `[__<id>__]` convention anywhere in the name, returning it as a structured field and removing it from all other parsed fields.

- **Milestone**: M1
- **Source**: MFP §2.15; MFS §4 (DDL queue hands completed downloads to PP with `[__issueid__]` tags); MFP §5 pass-through metadata bullet 3.
- **Notes**: M1-critical because the built-in DDL path (in the vertical slice) uses this tag as its snatch↔completion handshake. Renamer (PP) may embed it to make files self-identifying.

#### Scenario: Mid-name embedded ID extracted and removed

- **WHEN** `Batman 404 [__123456__] (1987).cbz` (corpus row 66) is parsed
- **THEN** the result carries `issue_id = "123456"` as a structured field, and all other fields are exactly as for `Batman 404 (1987).cbz` — `series_name = "Batman"`, issue value 404, year 1987 — with no trace of the tag in title, issue, volume, or annotation fields

#### Scenario: The tag is recognized anywhere in the name

- **WHEN** DDL-style placements `[__987654__] Saga 55 (2018).cbz` (leading) and `Saga 55 (2018) [__987654__].cbz` (trailing) are parsed
- **THEN** both yield `issue_id = "987654"` with otherwise identical normal results (`series_name = "Saga"`, issue value 55, year 2018), supporting the DDL snatch-to-completion handshake regardless of where the downloader placed the tag

#### Scenario: Absent tag yields None, and plain brackets are not IDs

- **WHEN** `Batman 404 (1987).cbz` and a non-conforming bracket group such as `Batman 404 [123456] (1987).cbz` are parsed
- **THEN** `issue_id` is None in both cases — only the exact `[__<id>__]` double-underscore convention populates the field, and the plain `[123456]` group is classified as an ordinary annotation

### Requirement: FRG-IMP-019 — Series title output and alternate title splits

The parser SHALL return the series title exactly as present in the name minus consumed designators, plus the normalization-folded matching variant, plus any alternate series/issue-title split implied by hyphen-delimited titles (`Series - Subtitle NN (Year)`, trailing `- Issue Title` forms), without corrupting titles whose words themselves contain hyphens.

- **Milestone**: M1
- **Source**: MFP §2.15 (alt_series/alt_issue), §4 item 20; MFP §5 Series title & matching support.
- **Notes**: Alternate splits are hints for series matching (search/metadata areas), carried as structured optional fields, not extra parse modes.

#### Scenario: Hyphen-delimited subtitle produces an alternate split

- **WHEN** `Batman - The Long Halloween 05 (1997).cbz` (corpus row 64) is parsed
- **THEN** the primary `series_name` is `Batman - The Long Halloween` with issue value 5 and year 1997, and the structured alternate fields carry `alt_series = "Batman"` and the subtitle `The Long Halloween` as the alternate issue-title hint — optional fields on the one result, not a second parse mode

#### Scenario: Trailing issue title after the issue number

- **WHEN** `Daredevil 600 - Mayor Fisk (2018).cbz` (corpus row 65) is parsed
- **THEN** `series_name = "Daredevil"`, issue value 600, year 2018, and `Mayor Fisk` is returned as the alternate/issue-title field — the post-dash words are never absorbed into the series name or misread as issue candidates

#### Scenario: Hyphenated title words survive uncorrupted

- **WHEN** `X-23 012 (2011).cbz` (corpus row 9) and `Star Wars Legacy II 03 (2013).cbz` (corpus row 72) are parsed
- **THEN** `series_name` is exactly `X-23` (the in-word hyphen triggers no alternate split; alternate fields are None) with issue value 12, and `Star Wars Legacy II` survives with the mid-title roman numeral intact and issue value 3

#### Scenario: Raw title and folded matching key are both returned

- **WHEN** `Amazing.Spider-Man.798.2018.Digital.Empire.cbr` (corpus row 11) is parsed
- **THEN** the result carries both the raw `series_name` (`Amazing Spider-Man`, designators and annotations removed, original casing preserved) and the normalization-folded matching key produced by the single shared normalization function (FRG-IMP-005), as two distinct fields

### Requirement: FRG-IMP-020 — Total, collision-free issue ordering keys

The system SHALL provide a single issue-number ordering/comparison implementation producing a total order that is collision-free across the supported issue vocabulary (integers, decimals, negatives, fractions, alpha suffixes, annual classification), used by parsing, matching, sorting, and renaming alike, with no magnitude-domain mixing or unparseable-sentinel values.

- **Milestone**: M1
- **Source**: MFP §2.3 (ord-sum scoring), §4 item 13 (collisions, `*1000` vs ord sums vs sentinels); MFP §5 Issue numbers bullet 5.
- **Notes**: Replaces `helpers.issuedigits`. Recommend a sort-key tuple (class, numeric, suffix rank) rather than a single scalar — design freedom, but the collision-free property is the requirement.

#### Scenario: Mixed-vocabulary values sort in the expected total order

- **WHEN** the ordering key is computed for the issue identities parsed from corpus rows 15, 16, 12, 24, and 18 — `-1` (Deadpool), `½` (Uncanny X-Men), `015.5` (Invincible), `15A` (Amazing Spider-Man), `027AU` (Wolverine)
- **THEN** sorting by the key yields `-1` < `½` (0.5) < `15A` (base 15 plus suffix, ordered deterministically relative to plain 15 by the suffix-rank rules) < `15.5` < `27AU`, and a fraction glyph `½` and a plain `0.5` issue of the same series compare equal in key only when they denote the same issue identity

#### Scenario: Distinct suffixes never collide

- **WHEN** ordering keys are generated for every pair of distinct issue identities over the corpus values plus generated combinations of base numbers with the full suffix vocabulary (AU, AI, INH, NOW, BEY, MU, HU, LR, DEATHS, ALPHA, OMEGA, seasonal names) — including suffix pairs whose character `ord()` sums are equal
- **THEN** no two distinct identities produce equal keys (zero collisions), demonstrating the replacement of Mylar's ord-sum scoring, `*1000` magnitude mixing, and `999999999999999` sentinels

#### Scenario: Total-order properties and single implementation

- **WHEN** a property test exercises the comparator over randomly generated triples of supported issue identities (including annual-classified issues alongside same-numbered regular issues), and the codebase is audited for comparator implementations
- **THEN** the comparison is reflexive-antisymmetric, transitive, and total (every pair comparable); an annual issue 1 and a regular issue 1 of the same series have distinct, deterministically ordered keys; and exactly one ordering implementation exists, imported alike by parsing, matching, sorting, and renaming code

### Requirement: FRG-IMP-021 — Corpus-driven regression suite

The parser SHALL be covered by a table-driven regression corpus seeded with the full 67-row corpus plus the 8 supplementary edge rows from the research report, grown over time such that every behavioral rule in this AREA has at least one positive and one adversarial corpus case, and every parser bug fix adds its reproducing row before the fix lands.

- **Milestone**: M1
- **Source**: MFP §3 (corpus rows 1–75); MFP §5 Quality, diagnostics & testing bullet 2; CLAUDE.md FRG-PROC-004 (tests traceable).
- **Notes**: "Full corpus strength IS M1" per milestone definition. Rows the research flags as fuzzy (25, 58) are pinned to the *desired* column, i.e. we assert the corrected behavior, not Mylar's. Each corpus row should be taggable to the requirement it evidences so the traceability matrix (FRG-PROC-005) can be generated.

#### Scenario: All 75 seed rows asserted with corrected expectations

- **WHEN** CI runs the table-driven corpus suite over MFP §3 rows 1–67 plus supplementary rows 68–75
- **THEN** every row asserts series name, issue (value/suffix/display), volume fields, year, booktype, classification, scan group, and issue-id exactly as tabled, with the research-flagged rows pinned to the corrected column — row 25 asserts issue 30 with `Cover B` as annotation, row 43 asserts volume 3 (not a lost roman numeral), row 50 asserts booktype `GN`, row 42 asserts no volume — and any deviation fails the build

#### Scenario: Every corpus row is traceable to requirement IDs

- **WHEN** the traceability-matrix generator consumes the corpus table
- **THEN** each row carries at least one `FRG-IMP-NNN` tag naming the requirement(s) it evidences (e.g. row 32 `Kick-Ass 3 01 (of 08) (2013).cbz` tagged FRG-IMP-011 and FRG-IMP-007; row 66 tagged FRG-IMP-018), every requirement FRG-IMP-001..020 is evidenced by at least one positive and one adversarial row, and the matrix in `docs/traceability/` regenerates from these tags without manual editing

#### Scenario: Zero-unhandled-exception sweep over a real-world name list

- **WHEN** the suite additionally sweeps a large real-world filename list (thousands of names harvested from actual library and indexer-title shapes, committed as a fixture) through `parse(name, reference_year=<pinned>)`
- **THEN** every input returns a structured result — success or reasoned failure — with zero unhandled exceptions across the entire sweep, enforcing the FRG-IMP-003 crash bar at corpus scale

#### Scenario: The corpus is additive-only and grows with every bug fix

- **WHEN** a parser bug is fixed, or the corpus file's history is audited
- **THEN** the fix's change includes a new corpus row reproducing the bug (added and failing before the fix, passing after), and no existing row has ever been deleted or weakened — expectation corrections are themselves recorded as deliberate pinned-behavior changes citing the governing requirement ID
