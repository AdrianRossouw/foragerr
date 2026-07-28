# imp — delta for m11-source-import-trust

## ADDED Requirements

### Requirement: FRG-IMP-026 — Issue-word filler stripping

The parser SHALL exclude a bare "Issue"/"Issues" filler word from the
parsed series title when that word immediately precedes the file's issue
evidence (an issue anchor `#` or the token selected as the issue number).
The rule is anchored and narrow: an "Issue"/"Issues" word not directly
followed by the issue evidence (e.g. mid-title usage) SHALL remain part
of the series title, and no other vocabulary changes are introduced.
The Humble naming idioms motivating this rule SHALL be pinned as
additive corpus rows under the FRG-IMP-021 regime, including the
`Vol. N`-with-no-issue shapes whose parse output (ordinal volume, no
issue) deliberately does not change — their resolution is the import
pipeline's job (FRG-PP-022), never the parser's.

#### Scenario: Filler before an anchored issue number is stripped

- **WHEN** "Strangelands Issues #8.cbz" is parsed
- **THEN** the series title is "Strangelands" and the issue value is 8

#### Scenario: Spaced anchor variant

- **WHEN** "SPAWN Issue # 279.cbz" is parsed
- **THEN** the series title is "SPAWN" and the issue value is 279

#### Scenario: Mid-title issue word is preserved

- **WHEN** a filename whose series title legitimately contains the word
  "Issue" not directly preceding the issue evidence is parsed
- **THEN** the word remains part of the series title — the strip rule
  never fires without the anchored adjacency

#### Scenario: Vol-N shapes keep their parse semantics

- **WHEN** "SPAWN Vol. 243.cbz" is parsed
- **THEN** the result carries ordinal volume 243 and no issue value —
  the corpus row pins that the parser does not reinterpret volumes as
  issues (FRG-IMP-012 field separation stands)
