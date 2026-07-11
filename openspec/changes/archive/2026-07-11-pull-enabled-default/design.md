# Design — pull-enabled-default

## Context

Owner instruction 2026-07-11 ("enable walksoftly by default") following the
empty-calendar diagnosis: `pull_enabled=false` + no UI toggle meant fresh
installs never saw external release data.

## Goals / Non-Goals

**Goal**: flip the default; keep opt-out intact; docs and risk posture
updated. **Non-goals**: settings-UI exposure, calendar banner states, any
fetch-behavior change — those are a separate candidate change.

## Decisions

1. **Config-default flip only** — no migration, no persisted-config
   rewrite. Honest consequence: first-run rendering wrote the literal
   `pull_enabled: false` into every pre-v0.5.1 install's config.yaml, and
   a file value is authority — so the new default reaches only fresh
   installs; existing installs keep false until the operator edits the
   file. A rewrite was rejected because an auto-rendered false and a
   deliberate operator false are indistinguishable in the file — the same
   never-guess-intent principle as the explicit-follows decision. The
   CHANGELOG and manual tell existing operators the one-line flip.
2. **Degraded-source behavior is the safety net** — the source is
   currently 523-down; a default-on install degrades to local metadata
   exactly per FRG-PULL-002 (verified live in-session). No retry/backoff
   changes needed.

## Risks / Trade-offs

- [Default third-party traffic from every install] → owner-accepted
  (RISK-039 note); opt-out preserved; hardened egress unchanged.
- [Existing config files pin false] → correct per Decision 1; the manual
  wording tells operators where the switch lives.

## Migration Plan

None. Rollback = revert.

## Open Questions

_None._
