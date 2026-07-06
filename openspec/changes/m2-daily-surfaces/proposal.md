## Why

M2 change 4 delivers the daily-use surfaces: after add/search/download/import
(M1) and mass library ingestion (ch3), the day-to-day loop still lacks its
review screens — what happened (history), what's missing (wanted), what's
banned (blocklist) — plus the two highest-value OPDS touches for the actual
iPad use case (Recent Additions, working search). It also pays down three
accepted residues that belong with this surface work: RISK-040's unbounded
blocked-retry history growth, and the two delete-files UX defects from the
manual audit (a checkbox that always 501s; a fully-implemented per-file delete
flow with zero callers).

## What Changes

- **History (FRG-API-011 + FRG-UI-010)**: paged `GET /api/v1/history` over
  `import_history` with event-type/series filters and nested series/issue
  (queue-endpoint pattern), plus an Activity → History screen. The event
  vocabulary's two writerless gaps close: `grabbed` rows are written at grab
  time and `download_failed` at failure time, so the single feed really is
  single-source (the operational `grab_history` match-key table is unchanged).
- **History integrity / RISK-040**: an identical blocked outcome (same event
  type, same canonical data payload) for the same download no longer writes a
  duplicate `import_blocked` row each retry cycle — the retry behavior itself
  is untouched. Risk register updated to mitigated.
- **Wanted (FRG-API-012 + FRG-UI-011)**: paged `GET /api/v1/wanted/missing`
  reusing the canonical derived query (`repo.wanted_issues`); a Wanted screen
  with per-issue interactive search and a search-all action. **The cutoff-unmet
  half of the baseline requirement is dropped** per the owner's M2 reshape
  (quality cutoffs parked to B) — the delta records this narrowing.
- **Blocklist (FRG-UI-017)**: `GET /api/v1/blocklist` (paged) +
  `DELETE /api/v1/blocklist/{id}`, and an Activity → Blocklist screen showing
  why each release was banned, with remove (release becomes grabbable again).
- **Command status push (FRG-SCHED-010)**: the one real gap closes — the
  `started` transition now emits `CommandStatusChanged` like queued/terminal
  do; a tagged test pins queued→started→completed reaching the WS client.
- **OPDS Recent Additions (FRG-OPDS-013)**: `/opds/recent` acquisition feed
  ordered by file import time (newest first), paginated, advertised on the
  root feed.
- **OPDS search (FRG-OPDS-007 option a)**: root feed advertises a search link;
  a valid OpenSearch description document; a templated search feed over series
  titles (id-only resolution, bound parameters, same unauthenticated-hostile
  posture and adversarial tests).
- **Delete-files defects (amending FRG-API-003 / FRG-UI-004)**:
  `DELETE /api/v1/series/{id}?deleteFiles=true` is implemented (each file
  routed through the recycle bin before the rows go) instead of returning 501;
  new `DELETE /api/v1/issuefile/{id}` wires the existing `delete_issue_file`
  flow; SeriesDetail's delete dialog stops lying and issue rows gain a
  delete-file action. User-initiated deletes record `source=manual`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `api`: FRG-API-011 (history endpoint elaborated; grabbed/download_failed
  writers; dedup scenario), FRG-API-012 (cutoff half REMOVED — plain
  wanted/missing only), FRG-API-003 (deleteFiles=true now implemented, 501
  scenario replaced).
- `ui`: FRG-UI-010, FRG-UI-011, FRG-UI-017 elaborated from baseline
  placeholders; FRG-UI-004 (series detail delete dialog + per-issue file
  delete).
- `sched`: FRG-SCHED-010 (started transition included in the push).
- `opds`: FRG-OPDS-013 elaborated; FRG-OPDS-007 flips from option (b) to
  implemented option (a).

## Impact

- **Code**: `importer/history.py` (+dedup helper, grabbed/failed writers via
  `search_ops/grab.py` and `downloads/tracking.py`), new `api/history.py`,
  `api/wanted.py`, `api/blocklist.py`, `api/issuefile.py` routers,
  `commands/service.py` (started event), `opds/router.py` (+recent, +search,
  +descriptor), `library/flows/edit_delete.py` (series delete-files wiring,
  manual source), frontend: three new screens + SeriesDetail changes + nav +
  a real pagination pattern.
- **DB**: none (no new tables; import_history gains rows, not columns).
- **Security docs**: OPDS search is new parsing of untrusted query input on
  the unauthenticated listener → threat-model delta + adversarial tests in the
  same change. Everything else rides existing surfaces.
- **Manual** (FRG-PROC-011): web-ui.md gains History/Wanted/Blocklist
  sections; reading-opds.md gains Recent + search; import.md's delete promise
  is fulfilled and reworded; library.md's 501 note replaced.
- **Dependencies / SOUP**: none.

## Non-goals

- No cutoff-unmet tab or quality-profile changes (parked to B).
- No notifications (NOTIF parked).
- No scheduled/periodic refresh (later milestone).
- No history pruning/retention policy (dedup removes the growth driver;
  retention is ch5 ops territory if still wanted).

## Approval

Covered by Adrian's standing FRG-PROC-009 grant of 2026-07-06 for all M2/M3
changes; recorded per the M1-style standing-grant model.
