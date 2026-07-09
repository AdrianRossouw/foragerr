# dep delta — going-public

## ADDED Requirements

### Requirement: FRG-DEP-014 — Open-source license (GPL-3.0)

The repository SHALL carry the GNU General Public License v3.0: the verbatim
GPL-3.0 text in `LICENSE` at the repository root, a matching
`license` declaration in `pyproject.toml`, and a license statement in the
`README.md` labelling. The three SHALL agree.

#### Scenario: License file present and declared

- **WHEN** the documentation-consistency checks run
- **THEN** `LICENSE` exists at the repo root containing the GPL-3.0 text,
  `pyproject.toml` declares the GPL-3.0 license expression, and `README.md`
  names GPL-3.0 and links to `LICENSE`

#### Scenario: License survives packaging metadata

- **WHEN** the backend package metadata is built or inspected
- **THEN** the license expression reported for the package is GPL-3.0
