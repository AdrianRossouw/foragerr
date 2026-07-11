# Design — m5-creators-screens

## Context

The v0.5.0 backbone exposes `GET /creators` (paged rows + aggregates,
bounded work refs), `GET /creators/{id}` (whole-series owned/total stats),
and the follow PUT. The design handoff §7/8 fixes both screens' anatomy.
The owner decision of 2026-07-11 (decisions.md) removes derived follows:
seeding goes, and v0.5.0-seeded rows are unseeded by marker.

## Goals / Non-Goals

**Goals**: explicit-only follows (backend amendment + data fix); the two
creator screens to design; series-detail credits strip; nav entry; manual +
screenshot refresh.

**Non-goals**: "More from" bibliography / person fetch (ch3); follow-driven
behavior of any kind; creator search; avatar images.

## Decisions

1. **Unseed as a marker-gated startup data fix, no migration.** Same
   `app_state` idiom as the backfill (`creators_unseed_done`): one
   UPDATE … WHERE followed AND follow_touched IS NULL, logged with the
   count. Rationale: it's data repair, not schema — and the keystore
   branch keeps 0017 uncontested. Runs before the backfill hook so a
   first-boot-after-upgrade can't seed-then-unseed within one start
   (ordering asserted in tests). Seeding code and its tests are deleted
   outright (the spec now forbids the behavior; the tripwire is the
   no-derived-follow test).
2. **Focus chip via a `seriesId` filter param on the list endpoint.**
   Server-side filter (`GET /creators?seriesId=`) beats shipping every
   creator to filter client-side, reuses the paging envelope, and gives
   series detail's strip its "view all" target
   (`/creators?seriesId=<id>`). URL carries the focus so back/refresh
   keep it — mirroring the Calendar's `?week=` precedent.
3. **Screens follow the house screen-triple pattern**;
   `screens/creators/CreatorsScreen.tsx` + `CreatorProfile.tsx` (+ module
   css + tests each). Avatar = a small shared component (initials from
   name, deterministic; gradient via two new `--avatar-gradient-*` tokens
   next to the logo-gradient tokens). Role chips reuse the FORMAT_CHIP
   pattern in `palettes.ts` (a `ROLE_CHIP` map keyed by the fixed
   vocabulary — data-layer colors, not brand tokens).
4. **Series-detail strip reads a `creators` field on the existing series
   credits query** — new lightweight endpoint parameter or a dedicated
   `GET /creators?seriesId=` call reused from Decision 2 (the strip IS the
   focused list, capped). No new resource shape.
5. **Optimistic follow toggles** with invalidation of the creators list +
   profile queries; failure rolls back the pill (house mutation pattern).
6. **Screenshot tour gains `creators-grid`** (deterministic:
   library-derived initials/counts from the PD-seeded demo instance) and
   every existing shot picks up the new nav entry.

## Risks / Trade-offs

- [Upgrade ordering: unseed must precede any UI read] → startup hook order
  is deterministic and tested; worst case a pre-unseed API read briefly
  shows a seeded follow — display-only, no behavior attaches to follows.
- [Grid size at scale (hundreds of creators)] → server paging already
  exists; the grid pages like the library index. Card spines are bounded
  (≤6 refs from the API).
- [Focus param widens the read API] → read-only filter over stored data,
  no egress, validated int; spec'd as part of FRG-UI-027's source notes
  rather than a new API requirement (FRG-API-023's shape is unchanged in
  kind — flag at gate if reviewers disagree).

## Gate-accepted divergences

Recorded at the m5-creators-screens gate (frontend-fidelity angle):

- **Errored credits strip renders as absent** on series detail — an API
  failure is visually identical to "no credits". Accepted: the strip is
  additive and non-load-bearing; the Creators screen surfaces the same
  failure loudly. Revisit if strip data ever drives an action.
- **Work-card progress uses house `ProgressStrip` styling** (20px,
  completeness-toned track) instead of the handoff's neutral 18px track —
  shell consistency over mock parity.
- **Grid minmax 340px / work grid 320px** vs the handoff's 362/340 —
  denser wrapping, cosmetic.

## Migration Plan

No schema migration. The unseed data fix is a one-time startup pass
(marker-gated, idempotent, logged). Rollback = revert the merge; unseeded
rows stay unfollowed (acceptable — the owner explicitly wants no derived
follows).

## Open Questions

_None blocking._
