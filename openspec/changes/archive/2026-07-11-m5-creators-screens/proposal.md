# m5-creators-screens

## Why

M5 chapter 2. The v0.5.0 backbone put creator credits and follows in the
database and API; nothing shows them yet. This change ships the two designed
creator surfaces (handoff §7 grid, §8 profile) and surfaces credits on
series detail — and it executes the owner decision from the v0.5.0
release-notes review (2026-07-11, `docs/process/decisions.md`): **follows
are explicit-only**, so the ≥2-series auto-follow seeding shipped in v0.5.0
is removed before any UI ever displays a seeded follow.

## What Changes

- **Explicit-only follows (FRG-CRTR-004 amended)**: threshold seeding is
  removed from reconciliation; a one-time data fix flips `followed = false`
  where `follow_touched IS NULL` (seeded rows are exactly the never-touched
  ones — the marker design makes them separable from explicit follows,
  which are untouched). A follow is always a user action.
- **Creators grid (FRG-UI-027)** at `/creators`, per handoff §7: cards with
  green-gradient initials avatars, name, `roles · N series`, a
  Follow/Following pill, and a row of library work cover spines; header
  count line (`N creators · M followed`); a followed-only filter; a
  creator-focus chip when arriving from a series-detail credit. The
  Creators nav entry ships here (shipped-screens rule, FRG-UI-023).
- **Creator profile (FRG-UI-028)** at `/creators/{id}`, per handoff §8:
  gradient header (large avatar, name, roles line, publishers line, Follow
  button), three stat columns (Series / Issues in library owned-of-total /
  Publishers), and the "In your library" work cards (cover, volume label,
  role chips, meta line, owned/total progress bar, click-through to series
  detail). The "More from <name>" external-bibliography section is ch3 —
  the profile renders without it.
- **Series-detail credits (FRG-UI-004 amended)**: a creators strip/section
  on series detail listing the series' credited creators (name, roles),
  each linking to the creator profile.
- **Manual + docs**: manual gains a Creators section; README screenshot
  refresh (nav gains Creators in every shot; a creators-grid shot joins
  the tour — deterministic, it's library-derived data).

## Capabilities

### Modified Capabilities

- `crtr`: FRG-CRTR-004 amended — explicit-only follows (seeding removed +
  unseed data fix).
- `ui`: new FRG-UI-027 (creators grid), new FRG-UI-028 (creator profile);
  FRG-UI-004 amended (credits section on series detail).

## Non-goals

- **No "More from <name>" bibliography** and no ComicVine person fetch —
  ch3 (m5-creator-suggestions), with its own egress/security spec.
- **No follow-driven behavior** — following changes display state only;
  no notification, no suggestion surfacing yet, never any download.
- **No creator search/sort beyond the designed surface** (name sort +
  followed filter; add more only if use demands).
- **No avatar images** — initials avatars per the design (CV person images
  are not fetched).

## Impact

- **Backend** (small): reconciliation seeding removal + the unseed data
  fix (a startup one-shot or migration-style data pass — decided in
  design), FRG-CRTR-004 test updates; possibly a `focus`/`series_id`
  filter param on the creators list endpoint for the focus chip (decided
  in design).
- **Frontend** (bulk): new `screens/creators/` (grid + profile + tests),
  avatar/gradient tokens, nav entry, series-detail credits section, query
  hooks for the creators API.
- **Security**: no new attack surface — displays already-sanitized stored
  strings; no new endpoints beyond a possible read filter param. No SOUP
  change.
- **Traceability**: FRG-UI-027/028 allocated; FRG-CRTR-004/FRG-UI-004
  amended; decisions.md entry recorded (2026-07-11).
- **Coordination**: no migration expected (data fix rides startup/backfill
  machinery, not schema); if one proves necessary it claims 0017 and the
  keystore branch shifts again — checked at merge either way.

## Approval

Approved under the M4–M7 standing grant (Adrian, 2026-07-10 — "M5 creators
& follows" enumerated), plus the explicit owner direction of 2026-07-11
(release-notes review): follows explicit-only, keep rolling M5. Gate
obligations unchanged.
