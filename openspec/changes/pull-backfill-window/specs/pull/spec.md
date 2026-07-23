# pull — delta for pull-backfill-window

## ADDED Requirements

### Requirement: FRG-PULL-010 — First-run backfill window

A pull refresh SHALL widen its fetch window to include the previous
`pull_backfill_weeks` ISO weeks (default 4, `0` disables, values above 12
clamped to 12) when — and only when — the pull store contains no stored
weeks. Backfilled weeks flow through the same fetch client, shipdate-derived
per-week storage, matching, and refresh-trigger pipeline as the standard
window (FRG-PULL-002/003/005); once any week is stored, subsequent refreshes
use the standard window only.

#### Scenario: Empty store backfills

- **WHEN** a pull refresh runs with `pull_backfill_weeks: 4` and no stored pull weeks exist
- **THEN** the fetch window covers the previous four ISO weeks in addition to previous/current/next, and fetched entries store and match through the normal pipeline under their shipdate-derived weeks

#### Scenario: Non-empty store never backfills

- **WHEN** a pull refresh runs and at least one pull week is already stored
- **THEN** the fetch window is the standard previous/current/next only — no historical week is requested

#### Scenario: Disable and cap

- **WHEN** `pull_backfill_weeks` is `0`, or configured above the cap
- **THEN** `0` performs no backfill even on an empty store, and an over-cap value is clamped to 12 with the effective value logged
