# Tasks — m5-creators-screens

## 1. Backend: explicit-only follows + focus filter

- [x] 1.1 Remove threshold seeding from `creators/reconcile.py` (+ its
      tests); add the no-derived-follow tripwire test (FRG-CRTR-004)
- [x] 1.2 Marker-gated startup unseed data fix (`creators_unseed_done`),
      ordered before the backfill hook; tests: seeded rows flip, explicit
      follows survive, one-shot marker, ordering (FRG-CRTR-004)
- [x] 1.3 `seriesId` filter param on `GET /api/v1/creators` (validated,
      paged as usual); tagged tests (FRG-API-023, FRG-UI-027)

## 2. Frontend: creators surfaces

- [x] 2.1 Query hooks + types for creators list/profile/follow; avatar
      component + gradient tokens; ROLE_CHIP palette map (FRG-UI-027,
      FRG-UI-028)
- [x] 2.2 `CreatorsScreen` grid to handoff §7: cards, pills, spines, count
      header, followed filter, `?seriesId=` focus chip, empty state
      (credits-gathering); nav entry + route (FRG-UI-027)
- [x] 2.3 `CreatorProfile` to handoff §8: gradient header, stats columns,
      in-library work cards with role chips + whole-series progress,
      not-found state; no "More from" section (FRG-UI-028)
- [x] 2.4 Series-detail creators strip (stored credits; absent when none),
      linking to profile / focused grid (FRG-UI-004)
- [x] 2.5 Vitest coverage with requirement ids in names: grid anatomy +
      aggregates, explicit-only follow toggle (single PUT, no other
      writes), filter + focus chip, empty state, profile header/stats/
      cards/not-found, strip presence/absence/navigation (FRG-UI-027,
      FRG-UI-028, FRG-UI-004, FRG-CRTR-004)

## 3. Docs, traceability, gate

- [x] 3.1 Manual Creators section; README tour refresh incl. new
      creators-grid shot (FRG-PROC-011/017)
- [x] 3.2 Registry flips (UI-027/028 → implemented; CRTR-004 stays
      implemented, amended in baseline spec via sync); matrix regen;
      soup_check green (FRG-PROC-002/005)
- [x] 3.3 CHANGELOG + v0.5.2 bump on-branch (v0.5.1 was taken by pull-enabled-default); full suites + e2e green;
      tiered gate (medium) + Codex; keystore coordination check
      (FRG-PROC-007/013)
