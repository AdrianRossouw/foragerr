# dev-process delta — roadmap-reshape

## MODIFIED Requirements

### Requirement: FRG-PROC-011 — Manual and README kept in sync with the application

The project SHALL maintain a user and administrator manual in `docs/manual/`, covering
user-facing behavior (what the application does and how to operate it) and
administration (deployment, configuration, environment variables, network exposure),
together with the repository `README.md` as top-level labelling/technical
documentation stating what the project is, its security and regulatory posture, the
development process (way of working), installation instructions, and (while the
repository is public) the roadmap and license/contribution posture per FRG-PROC-014.
The `README.md` is a controlled document on the same footing as the manual: a change
that alters any fact the README states — features, posture, process, installation,
roadmap milestones or their labels — SHALL update the README within the same change
(owner instruction 2026-07-10). Every OpenSpec change proposal SHALL declare its
manual impact — the manual/README sections it adds or updates, or an explicit "no
manual impact" statement with rationale. A change that alters manual-documented
behavior SHALL update the affected sections within the same change, before it merges
to `main`, and the merge gate SHALL verify that the declared manual impact was
carried out.

#### Scenario: Change alters documented behavior

- **WHEN** a change alters or adds user-facing or administrative behavior
- **THEN** the same change updates the affected `docs/manual/` sections before the change merges to `main`

#### Scenario: Change alters a fact the README states

- **WHEN** a change alters anything the README asserts — including roadmap
  milestone assignments, posture statements, or process descriptions
- **THEN** the same change updates the affected README section before merging,
  and the doc-consistency tests hold README claims to repository state (e.g.
  roadmap items citing requirement IDs carry the registry's milestone)

#### Scenario: Manual impact declared at proposal time

- **WHEN** an OpenSpec change proposal is authored
- **THEN** it contains a manual-impact declaration (sections touched, or "none" with rationale), reviewable at the FRG-PROC-009 approval gate

#### Scenario: Gate verifies sync

- **WHEN** a change reaches its merge gate
- **THEN** the gate confirms the manual matches the change's declared manual impact, and a mismatch blocks the merge until resolved
