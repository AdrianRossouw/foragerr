## MODIFIED Requirements

### Requirement: FRG-QUAL-001 — Format profile entity

The system SHALL define a format profile as a named, ordered list of allowed comic container formats (at minimum `cbz`, `cbr`, `pdf`) expressing preference from least to most preferred, together with a cutoff format at or above which an issue is considered satisfied and no further upgrades are sought; formats below a profile's lowest allowed rung SHALL be rejected for series using that profile.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §4 (QualityProfile: ordered qualities + cutoff), §608 (comic contraction to a short format ladder).
- **Notes**: The M1 default (see FRG-QUAL-002) makes this concrete without user configuration; profile *editing* UI is FRG-QUAL-005 (M2). This is the entity FRG-SER-001 references and FRG-SRCH-007 uses as its first comparator rung.

#### Scenario: Profile persists a named ordered format ladder with a cutoff

- **WHEN** a format profile is created with the ordered rungs `cbr < cbz` (least to most preferred) and cutoff `cbz`
- **THEN** the persisted profile row exposes its name, the ordered rung list preserving `cbr` below `cbz`, and the cutoff `cbz`, and the ordering is stable across reads

#### Scenario: Format below the lowest allowed rung is rejected

- **WHEN** a consumer evaluates a `pdf` release for a series whose profile allows only `cbr < cbz`
- **THEN** the release is rejected as below the profile's lowest allowed rung, with the format-below-floor reason recorded, and no file is accepted for the issue

#### Scenario: Allowed format above the current file but below cutoff is an upgrade

- **WHEN** a series using a `cbr < cbz` cutoff-`cbz` profile has a `cbr` file and a `cbz` release becomes available
- **THEN** the `cbz` release is treated as an upgrade over the existing `cbr` file because it is a higher allowed rung not yet at satisfied-and-frozen state

#### Scenario: Cutoff halts further upgrades

- **WHEN** a series using the same profile already holds a file at the cutoff format `cbz`
- **THEN** the issue is reported as satisfied and no further upgrade is sought even if another allowed `cbz` release appears

### Requirement: FRG-QUAL-002 — Default profile seeded on first run

The system SHALL seed a usable default format profile (ordered `pdf < cbr < cbz`, cutoff `cbz`) at first run and assign it to newly added series unless another profile is chosen, so that the acquisition and upgrade paths are fully defined without any profile configuration.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §4 (default profiles); critic BLOCKER (M1 referrers need a concrete profile to test against).
- **Notes**: Removes the "trivial profile" degradation caveat the SER/SRCH referrers would otherwise each need; only FRG-PP-005 had recorded it.

#### Scenario: First run seeds exactly one default profile with the specified ladder

- **WHEN** migrations run against a freshly initialized (empty) database
- **THEN** exactly one default format profile exists with rungs ordered `pdf < cbr < cbz` and cutoff `cbz`, and it is marked as the default

#### Scenario: Re-running migrations does not duplicate the default

- **WHEN** the migration set is executed a second time against a database that already contains the seeded default
- **THEN** the default profile count remains exactly one and its ladder and cutoff are unchanged (idempotent seed)

#### Scenario: New series without a specified profile is auto-assigned the default

- **WHEN** a series is added without specifying a format profile
- **THEN** the created series references the seeded default profile via its profile foreign key

#### Scenario: Explicit profile choice overrides the default on add

- **WHEN** a series is added with an explicitly chosen non-default profile
- **THEN** the created series references the chosen profile, not the seeded default
