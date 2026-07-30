# review-experience-2 — tasks

## 1. md5 dedupe (FRG-SRC-015, MODIFIED FRG-SRC-004)

- [ ] 1.1 Migration 0032: `source_entitlements.duplicate_of` (nullable) +
      `(source_id, md5)` index; forward-only
- [ ] 1.2 Sync-time linking (same source, same stored md5, `new` rows
      only; canonical = earliest; insert path parks newcomers) — decided
      rows never re-linked
- [ ] 1.3 Startup backfill, one-shot/idempotent: link existing sets only
      when every member is still `new`
- [ ] 1.4 `duplicate` review state wired through counts, default views,
      filters, grab/accept/bulk guards (stays outside
      `_ACCEPTABLE_REVIEW_STATES`); restore extended to duplicate rows
      (clears pointer, recomputes proposal)
- [ ] 1.5 Resources: canonical row exposes copy count + copy bundle
      identities; rows expose `review_status = duplicate`
- [ ] 1.6 Tests (tagged FRG-SRC-015 / FRG-SRC-004): link-at-sync,
      backfill all-new-only, no-relink-of-decided, null-md5 never links,
      counts exclude copies, grab/accept refusal, restore round-trip

## 2. Picker: id paste + collected-edition cue (MODIFIED FRG-UI-039)

- [ ] 2.1 Candidate resources (lookup + suggest) gain the derived
      collected-cues flag from the shared booktype vocabulary; no
      ranking change
- [ ] 2.2 `EntitlementSearch`: pasted URL/id routes to the FRG-API-026
      volume-id hook, renders the resolved volume as a pickable
      candidate; unknown id shows the not-found note
- [ ] 2.3 Badge rendering (reuse BookTypeBadge or equivalent, soft
      wording); group-header picker inherits (no fork)
- [ ] 2.4 Tests: backend flag derivation (synthetic titles); vitest for
      id-path pick, not-found note, badge presence + soft wording,
      FRG-UI-039 in names

## 3. Grouping: containment merge + within-group order (MODIFIED FRG-UI-029)

- [ ] 3.1 Server: display-group merge of containment-related stripped
      keys (contiguous-run rule, same primitive as the FRG-SRC-010
      floor); sweep key untouched; shared-fold docstring amended to name
      the sanctioned difference
- [ ] 3.2 Server: parsed (volume_ordinal, issue_number) sort key on the
      entitlement resource (parser derivation, single fold)
- [ ] 3.3 Frontend: sort group members by the server key (unknowns
      last, then name); merged-group labeling handles contained-key
      names (no dangling prefix derivation)
- [ ] 3.4 Duplicates filter + copies chip + dimmed Restore presentation
      (FRG-UI-029 scenarios)
- [ ] 3.5 Tests: fold-merge cases (synthetic two-name franchise), sort
      order incl. unknowns, sweeps still exact-fold (regression), vitest
      list presentation

## 4. Docs + verification

- [ ] 4.1 `docs/manual/user/sources.md` review section: duplicates,
      filter, group order, picker id paste + cue
- [ ] 4.2 Registry statuses + trace regen; full backend (xdist) +
      frontend (serialized) green; comment/soup/risk tools exit 0; e2e
      green (rig paused if constrained); live-rig verification of the
      Revival pairs collapsing and Luther Strode grouping/ordering
