# Tasks — m5-creator-suggestions

## 1. Backend

- [x] 1.1 CV client: `get_person_volumes(cv_person_id)` (person/4040
      detail → sanitized stubs) + `get_volumes_by_ids(ids)` (pipe-filter
      batch hydration); client tests pin both request paths
      (FRG-CRTR-005)
- [x] 1.2 Migration 0018 (`creator_bibliography` + stamp);
      `creator-bibliography-fetch` command (dedup, cap 24 newest-first,
      not-in-library exclusion at fetch, replace + stamp, failure keeps
      cache); tagged tests incl. failure/atomicity/no-acquisition
      (FRG-CRTR-005)
- [x] 1.3 `GET /creators/{id}/bibliography` (cache + live in-library
      anti-join, state fresh/pending, cold/stale enqueue dedup, no
      CV in handler — asserted); tagged tests (FRG-API-024)

## 2. Frontend

- [x] 2.1 Bibliography query hook (+ WS invalidation on command
      completion) and profile "More from" section per handoff §8: cards,
      Add hand-off into the standard add flow, pending/gathering state,
      absent-when-empty; vitest with requirement ids (FRG-UI-028)

## 3. Docs, gate, release — M5 CLOSES

- [x] 3.1 Manual Creators paragraph + RISK-011 note; registry flips;
      baseline sync; matrix regen (FRG-PROC-005/006/011)
- [x] 3.2 CHANGELOG v0.5.5 + bump on-branch; suites + e2e green; gate
      (medium: 2 angles + Codex) + fixes; keystore coordination check
      (0018 claimed → they take 0019); merge, tag, release, archive —
      then STOP for owner review (grant amendment 2026-07-11)
      (FRG-PROC-007/013)
