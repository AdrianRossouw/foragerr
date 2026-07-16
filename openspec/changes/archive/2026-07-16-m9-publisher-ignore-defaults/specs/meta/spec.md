# meta — m9-publisher-ignore-defaults deltas

## MODIFIED Requirements

### Requirement: FRG-META-007 — Series search

The system SHALL provide a ComicVine series search by name (volumes endpoint with per-word name filters) that paginates to a bounded result count and annotates each candidate with plausibility signals — publication-year range, issue-count sanity for a target issue when given, already-in-library flag — and SHALL exclude publishers on a configurable ignore list. Ignore-list entries match case-insensitively, either exactly or — when an entry contains `*` — as a substring of the publisher name with the `*` removed (so `Panini*` covers Panini Verlag/España/France). Excluded volumes are counted and the count reported alongside the results (never a silent drop), and an explicit include-ignored query mode SHALL return them flagged as ignored rather than omitting them.

- **Milestone**: M1; M9 (m9-publisher-ignore-defaults: wildcard matching, hidden-count reporting, include-ignored mode)
- **Source**: mylar-comicvine.md §1.6 (findComic heuristics), §5; mylar-feature-surface.md capability map META (ignored-publishers); Mylar `ignored_publisher_check` wildcard semantics (`.reference/mylar3/mylar/helpers.py`); M9 finding F17 (`docs/research/m9-user-sim-findings.md`).
- **Notes**: Keep Mylar's plausibility *annotations* but let the user (and the add flow) make the final choice — signals annotate and, since m4-add-new, order candidates (FRG-META-015); they never hard-drop except the publisher ignore list and never auto-pick. Result cap ~1000 with a visible truncation warning. The recoverable-count posture (vs Mylar's silent drop) is what makes a shipped default list (FRG-META-020) acceptable.

#### Scenario: Candidates annotated with plausibility signals, no auto-pick

- **WHEN** a known title is searched
- **THEN** each returned candidate carries plausibility annotations — similarity on the shared matching key, publication-year proximity, issue-count sanity for a target issue when supplied, and an already-in-library (`haveit`) flag for a series already present — and the search returns the annotated candidate list ordered per FRG-META-015 without auto-selecting one.

#### Scenario: Ignored-publisher volumes excluded but counted

- **WHEN** the results include volumes whose publisher matches the configurable ignore list (exactly, or via a `*` wildcard entry as a case-insensitive substring)
- **THEN** those volumes are absent from the returned candidates by default, the response reports how many were excluded, and other plausibility signals only annotate and order (do not hard-drop) the remaining candidates.

#### Scenario: Include-ignored mode returns flagged results

- **WHEN** the same search is issued with the explicit include-ignored option
- **THEN** the previously excluded volumes are returned in the candidate list, each flagged as ignore-listed, so a reader can recover a hidden edition without editing configuration.

#### Scenario: Bounded result count with truncation warning

- **WHEN** a search would exceed the bounded result cap
- **THEN** the results are truncated to the cap and a visible truncation warning accompanies them.

## ADDED Requirements

### Requirement: FRG-META-020 — Curated default publisher ignore list

The system SHALL seed `comicvine_ignored_publishers` on fresh installs with a documented, curated default list of foreign-market reprint publishers (wildcard entries permitted), chosen so that publishers of original material are never on the default list. A persisted configuration keeps its stored value across upgrades — the new default applies only where no value was previously rendered — and the manual documents both the default list and how an upgraded install opts in.

- **Milestone**: M9 (m9-publisher-ignore-defaults)
- **Source**: M9 finding F17 — the #1 Add New result for "Ultimate Spider-Man" was a German Panini reprint (Marvel's 2024 ongoing ranked 9th); owner approval 2026-07-16. Upgrade semantics follow the `pull_enabled` precedent (v0.5.1).
- **Notes**: Conservative curation is a requirement, not a preference: Les Humanoïdes Associés publishes originals (The Incal, Barbarella) and stays OFF the default list; the recoverable hide (FRG-UI-032) is the safety valve for anything the default over-catches. The list constant lives in one place (config field default) so Settings, docs, and tests reference the same value.

#### Scenario: Fresh install seeds the default list

- **WHEN** foragerr first runs against an empty config directory and renders its documented `config.yaml`
- **THEN** `comicvine_ignored_publishers` is rendered with the curated default list, and a subsequent series search excludes (and counts) matching-publisher volumes out of the box.

#### Scenario: Upgraded install keeps its stored value

- **WHEN** foragerr starts against a `config.yaml` that already carries a `comicvine_ignored_publishers` value (including the empty string rendered by older releases)
- **THEN** the stored value is used unchanged — the new default does not overwrite it.
