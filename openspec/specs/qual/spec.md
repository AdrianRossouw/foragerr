# QUAL — Format & Quality Profiles Specification

## Purpose

Defines the format/quality-profile entity that the library, search, and post-processing
areas depend on (referenced by FRG-SER-001/005/006, FRG-SRCH-004/007, FRG-API-003,
FRG-PP-005/013/014). This is the comic-domain contraction of Sonarr's quality-profile
machinery (sonarr-architecture.md §4, §608): comics have far fewer meaningful "qualities"
than video, so the profile reduces to an ordered list of container formats plus a cutoff,
extended at M2 by release-scoring and size bounds. Depth is baseline per the Phase 2 scope
decision; scenario elaboration happens in the implementing milestone change.

## Requirements

### Requirement: FRG-QUAL-001 — Format profile entity

The system SHALL define a format profile as a named, ordered list of allowed comic container formats (at minimum `cbz`, `cbr`, `pdf`) expressing preference from least to most preferred, together with a cutoff format at or above which an issue is considered satisfied and no further upgrades are sought; formats below a profile's lowest allowed rung SHALL be rejected for series using that profile.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §4 (QualityProfile: ordered qualities + cutoff), §608 (comic contraction to a short format ladder).
- **Notes**: The M1 default (see FRG-QUAL-002) makes this concrete without user configuration; profile *editing* UI is FRG-QUAL-005 (M2). This is the entity FRG-SER-001 references and FRG-SRCH-007 uses as its first comparator rung.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A profile allowing `cbz > cbr` with cutoff `cbz` accepts a cbr release for a series with no file, treats a later cbz as an upgrade, and rejects a pdf release as below the profile's allowed rungs.

### Requirement: FRG-QUAL-002 — Default profile seeded on first run

The system SHALL seed a usable default format profile (ordered `pdf < cbr < cbz`, cutoff `cbz`) at first run and assign it to newly added series unless another profile is chosen, so that the acquisition and upgrade paths are fully defined without any profile configuration.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §4 (default profiles); critic BLOCKER (M1 referrers need a concrete profile to test against).
- **Notes**: Removes the "trivial profile" degradation caveat the SER/SRCH referrers would otherwise each need; only FRG-PP-005 had recorded it.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A freshly initialized instance has exactly one default profile, and a series added without specifying a profile references it.

### Requirement: FRG-QUAL-003 — Release preferred-term scoring

The system SHALL support per-profile preferred and rejected terms (release-group, edition, and title tokens) that contribute a numeric score to a candidate release, feeding the release-decision comparator after the format rung, as the comic-domain analogue of Sonarr custom formats.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §3.2/§4 (custom-format scoring); mylar-feature-surface.md IDX/SRCH (ignore-words, scan-group scoring).
- **Notes**: Consumes the scan-group/annotation signals FRG-IMP flags at parse time. Second comparator key after FRG-QUAL-001's format rung in FRG-SRCH-007.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Given two same-format candidates, the one matching a preferred release-group term outranks the other, and a candidate matching a rejected term is refused.

### Requirement: FRG-QUAL-004 — Per-profile size bounds

The system SHALL allow optional minimum and maximum file-size bounds per profile, rejecting candidate releases outside the bounds during the decision stage.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §3.2 (size specifications); mylar-feature-surface.md SRCH (min/max size).
- **Notes**: Decision-engine specification, not a comparator; pairs with FRG-SRCH-004 accept/reject specs.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A release smaller than the profile minimum or larger than the maximum is rejected with a recorded reason.

### Requirement: FRG-QUAL-005 — Profile management UI and API

The system SHALL expose create/read/update/delete of format profiles through the API and a settings UI, including reordering formats, setting the cutoff, and editing preferred/rejected terms and size bounds, with profiles in use by series protected from deletion.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.1 (profile resources); mylar-feature-surface.md UI (config forms).
- **Notes**: Reuses the generic schema-form renderer FRG-UI/FRG-API promote to M1; the entity and default (QUAL-001/002) are M1, only management is M2.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A profile can be created, reordered, and assigned via the API; deleting a profile referenced by a series is refused with a clear error.
