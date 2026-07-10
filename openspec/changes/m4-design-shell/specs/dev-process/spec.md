# dev-process delta — m4-design-shell

## ADDED Requirements

### Requirement: FRG-PROC-017 — Regenerable README screenshots

The README tour's screenshots SHALL be regenerable by one command
(`tools/refresh-readme-shots.sh`): it starts the application against the
public-domain demo library, populates it when empty, captures the tour's
screen set via the committed capture script, optimizes every image to the
in-repo asset budget (≤ ~300 KB), and exits non-zero if any expected shot is
missing or over budget. A change that alters the shipped UI's appearance
SHALL re-run the tool and commit the refreshed assets before merging, so the
public labelling never lags the shipped design.

#### Scenario: One command produces the full tour set

- **WHEN** `tools/refresh-readme-shots.sh` runs on a machine with the demo
  library available
- **THEN** every screenshot the README embeds is regenerated at the expected
  path within budget, and the tool exits zero only when the set is complete

#### Scenario: UI-affecting changes refresh the tour

- **WHEN** a change alters the shipped UI's appearance
- **THEN** the same change commits refreshed README assets produced by the
  tool, verified at the merge gate

#### Scenario: Structural pin without the demo environment

- **WHEN** the documentation-consistency tests run in a hermetic environment
- **THEN** they verify the tool exists and is executable and that the README's
  embedded assets exactly match the capture script's shot set, without
  requiring the demo library or a browser
