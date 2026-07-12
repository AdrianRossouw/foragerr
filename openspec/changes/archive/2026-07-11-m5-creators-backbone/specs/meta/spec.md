# Delta: meta — m5-creators-backbone

## MODIFIED Requirements

### Requirement: FRG-META-006 — Issue mapping

The system SHALL map each ComicVine issue to an issue record — issue ID, number, title, cover date, store date, image URLs — preserving non-integer issue numbers verbatim alongside a computed sort key, defaulting missing dates to NULL, and SHALL surface (not silently skip) issues lacking an issue number. When the response row carries `person_credits`, the mapped record SHALL additionally carry typed credit entries (CV person id, sanitized display name, verbatim + normalized role, per FRG-CRTR-001); an absent, empty, or malformed credits value SHALL map to an empty credit list without affecting the rest of the issue mapping.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.5 (GetIssuesInfo; unnumbered issues skipped; singleIssue person credits); sonarr-architecture.md §1.1 (decimal/string issue numbers).
- **Notes**: Divergence: Mylar silently drops unnumbered issues; foragerr records them unmonitored with a warning so have/total counts remain honest. Mylar's digital-date prose heuristic is dropped (unreliable; store date suffices). m5-creators-backbone: credits mapping added — sanitation and role normalization are FRG-CRTR-001's contract; this requirement only guarantees the mapping is total (credits present → typed entries, anything else → empty list, never an error).

#### Scenario: Non-integer issue numbers preserved verbatim as TEXT with a sort key

- **WHEN** a fixture volume contains issues `1`, `1.5`, `1.MU`, and `½`
- **THEN** each issue number is stored verbatim as TEXT (not coerced to a number) alongside a computed sort key that orders them correctly.

#### Scenario: Missing dates map to NULL, not a date sentinel

- **WHEN** an issue omits its store date
- **THEN** the mapped store date is NULL — never `'0000-00-00'` or any sentinel string.

#### Scenario: Unnumbered issue is surfaced, not dropped

- **WHEN** a fixture volume includes an issue lacking an issue number
- **THEN** the issue is recorded (unmonitored) with exactly one visible "unnumbered issue" warning rather than being silently skipped, keeping have/total counts honest.

#### Scenario: Credits map totally — entries or an empty list, never an error

- **WHEN** fixture issue rows carry (a) well-formed `person_credits`, (b) no credits field, and (c) a malformed credits value
- **THEN** (a) maps to typed credit entries, (b) and (c) map to an empty credit list with the issue otherwise mapped normally, and no row raises or is skipped
