# pull-enabled-default

## Why

Owner decision (Adrian, 2026-07-11): the Calendar should show the week's
releases out of the box. Today `pull_enabled` defaults to `false` and is
configurable only via env/config file, so a fresh install's Calendar shows
only the local-metadata half — usually an empty agenda — with no hint why
(surfaced by the owner's own "calendar is not showing any releases" report;
diagnosis in-session 2026-07-11).

## What Changes

- **`pull_enabled` defaults to `true`** (config default + documented
  rendering + default-asserting test). Everything else about FRG-PULL-002
  is unchanged: same hardened egress profile, same error handling, same
  degraded-health surfacing, and setting `pull_enabled=false` still opts
  out completely (no third-party traffic, task no-ops, view renders from
  local metadata).
- Manual (`docs/manual/admin/configuration.md` §Weekly pull + config
  table) reworded from opt-in to on-by-default-with-opt-out.
- RISK-039 register row gains the posture note: default-on means every
  install issues scheduled traffic to the unofficial source; accepted by
  owner decision. `decisions.md` entry recorded.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `pull`: FRG-PULL-002 amended — default-on scenario added; the
  opt-in-notes language replaced by opt-out.

## Non-goals

- No settings-UI toggle for `pull_enabled`/`pull_source_url` (a separate
  candidate change, with the calendar source-status banner).
- No change to fetch windows, cadence, clamps, or error handling.
- No calendar UI changes.

## Impact

- **Backend**: one config default + description; one test assertion flips.
- **Security**: posture change, not surface change — same egress path,
  now exercised by default. RISK-039 note in the same change
  (FRG-PROC-006). Note: the source is currently returning 523s (origin
  down); the default-on install degrades gracefully exactly as spec'd —
  verified live in-session.
- **Docs**: manual §Weekly pull + config table; decisions.md.
- **Coordination**: tiny diff off main in its own worktree; merges
  independently of the in-flight m5-creators-screens branch (no file
  overlap except decisions.md, resolved at merge).

## Approval

Direct owner instruction, Adrian 2026-07-11: "enable walksoftly by
default." Recorded in decisions.md; per-change gate obligations unchanged
(small tier).
