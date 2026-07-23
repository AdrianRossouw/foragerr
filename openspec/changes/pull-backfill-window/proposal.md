# pull-backfill-window — first-run pull history backfill

## Why

A fresh install's Calendar starts empty until the next weekly cycle gives it
one week of releases — a new operator sees a bare screen instead of the
discovery surface the pull list is meant to be (owner request 2026-07-23,
live rig session: "a fresh install would like to see what they missed out
on"). The source serves historical weeks cheaply (~240 KB/week, verified
against talkhard weeks 28–29).

## What Changes

- When a pull refresh runs and the pull store is **empty** (fresh install,
  or an operator who cleared it), the fetch window widens to include the
  previous `pull_backfill_weeks` weeks (new setting, default 4, `0`
  disables, capped at 12), in addition to the standard
  previous/current/next window. Entries file through the existing
  shipdate-derived weekly storage, matching, and refresh-trigger pipeline
  unchanged.
- Backfill is inherently one-shot: once any week is stored the store is
  non-empty and every later refresh uses the standard window — no repeated
  historical traffic, no config migration needed.
- Week fetches within a run stay sequential over the existing hardened
  client; a backfill run is at most ~15 requests to the source, once per
  install lifetime.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `pull`:
  - **ADDED** `FRG-PULL-010 — First-run backfill window` (layered beside
    FRG-PULL-002/003/009, which are untouched; the M6 layering lesson —
    no MODIFIED restatement needed).

FRG-PULL-010 is allocated in the registry by this proposal.

## Impact

- Code: `pull/commands.py` fetch-window selection + `config.py` setting;
  tests for empty-store widening, non-empty-store non-widening, and the
  cap/disable values.
- Docs: `configuration.md` row for `pull_backfill_weeks`; no manual
  section change otherwise (Calendar behavior is unchanged, just populated
  sooner).
- No new attack surface: same source, same egress profile, same parser
  caps, bounded request count (FRG-PROC-006: no security-doc delta needed
  beyond noting the bounded fan-out).

## Non-goals

- Backfilling on every refresh, or refetching historical weeks that age
  out — the window widens only from an empty store.
- Historical depth beyond the cap (a month-ish is discovery; a year is an
  archive — different feature).
- Backfilled-week cover fetching or CV enrichment beyond what matching
  already does (the budget lanes work, M11, governs that).

## Approval

_Pending owner approval (FRG-PROC-009). Requested by Adrian 2026-07-23
("could we also back fill like a month or so from the source? i just
figure a fresh install would like to see what they missed out on")._
