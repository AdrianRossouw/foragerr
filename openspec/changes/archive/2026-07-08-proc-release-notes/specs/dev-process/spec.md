# dev-process Spec Delta

## MODIFIED Requirements

### Requirement: FRG-PROC-013 — Release tagging

Every change merged to `main` from change 7 (`m1-ui-opds-deploy`) onward SHALL be
marked by an annotated git tag on its merge commit, following SemVer: completing a
milestone sets the MINOR line (M1 = 0.1.x, M2 = 0.2.x, M3 = 0.3.x) and each
subsequent merged change within a milestone increments PATCH. The first tag SHALL be
`v0.1.0` at change 7's merge (M1 feature-complete) and `v0.1.1` at change 8's merge
(M1 acceptance-certified). The tag message SHALL name the change id and the FRG
requirement refs the change implements. Tags — together with the `main` branch they
point into — SHALL be pushed to `origin` when created, so every tag is a restore
point that survives loss of the working environment. Tags SHALL never be moved or
deleted once pushed; a bad release is corrected by a new PATCH tag.

Every such release SHALL additionally be recorded as **first-class, auditable release
notes**, so the release history is self-documenting rather than reconstructable only
from tag messages:

- a `CHANGELOG.md` entry at the repository root for the release version, in a
  Keep-a-Changelog-style format, listing the user- and administrator-facing changes
  grouped as Added / Changed / Fixed / Security, the FRG requirement ids the release
  delivers, and any upgrade or migration notes;
- the backend `pyproject.toml` `version` set to the release version, so the running
  application reports its true version rather than a stale placeholder;
- a published GitHub Release (`gh release create`) for the tag, carrying that
  CHANGELOG entry as its body.

The `CHANGELOG.md` entry and the `pyproject.toml` version bump SHALL land in the
**same merged change** as the code they describe, before it merges to `main`; the
annotated tag and the GitHub Release SHALL be created immediately after the merge
commit exists, in the same merge gate, from that same CHANGELOG entry. A release is
not complete until its CHANGELOG entry, tag, pushed `main`, and GitHub Release all
exist. This requirement applies **retroactively** to every tag created before it was
adopted: `CHANGELOG.md` and a GitHub Release SHALL exist for each existing tag
(v0.1.0 through v0.2.8), reconstructed from their tag messages and archived change
proposals.

#### Scenario: Change merge creates a tag

- **WHEN** a change merges to `main` at or after change 7
- **THEN** the merge gate creates an annotated SemVer tag on the merge commit whose message names the change id and its FRG refs

#### Scenario: Tags are pushed restore points

- **WHEN** a tag is created
- **THEN** the tag and `main` are pushed to `origin` in the same gate, and checking out the tag reproduces the released tree

#### Scenario: Tags are immutable

- **WHEN** a defect is found in a tagged release
- **THEN** the fix lands as a new merged change with a new PATCH tag; the existing tag is never moved or deleted

#### Scenario: Release carries a CHANGELOG entry and a matching version

- **WHEN** a change that will be tagged as a release merges to `main`
- **THEN** the same change has added its version's `CHANGELOG.md` entry (Added/Changed/Fixed/Security + FRG refs + upgrade notes) and set `backend/pyproject.toml` `version` to the release version, before the merge

#### Scenario: Release is published as a GitHub Release

- **WHEN** a release tag is created and pushed
- **THEN** a GitHub Release is published for that tag in the same gate, carrying the CHANGELOG entry as its body

#### Scenario: The release record is complete for existing tags

- **WHEN** the release-notes requirement is adopted
- **THEN** `CHANGELOG.md` and a published GitHub Release exist for every prior tag (v0.1.0..v0.2.8), reconstructed from tag messages and archived proposals
