## 1. History backbone (FRG-API-011)

- [x] 1.1 Event writers: `EVENT_GRABBED` at grab time (search_ops/grab.py,
      beside the grab_history insert) and `EVENT_DOWNLOAD_FAILED` at failure
      time (downloads/tracking.py process_failures). Tests: grab→import cycle
      yields both rows sharing downloadId. [FRG-API-011]
- [x] 1.2 `record_event_deduped` in importer/history.py (newest blocked/failed
      row for downloadId, identical event_type + canonical data → skip); used
      by both pipeline not-approved sites. Tests: N identical retries → 1 row;
      changed reasons → new row; retry loop untouched. Risk register RISK-040
      → Mitigate. [FRG-API-011, FRG-PROC-006]
- [x] 1.3 `GET /api/v1/history` (queue pattern: paginate + batch series/issue
      + eventType/seriesId filters + sort whitelist). Tagged tests incl.
      filters + 400 on bad sortKey. [FRG-API-011]

## 2. Wanted + blocklist APIs (FRG-API-012, FRG-UI-017 surface)

- [x] 2.1 `GET /api/v1/wanted/missing` over repo.wanted_issues (paged, nested
      series). Tests: derived semantics (import removes, delete returns), no
      stored status. [FRG-API-012]
- [x] 2.2 `GET /api/v1/blocklist` (paged, nested series/issue) +
      `DELETE /api/v1/blocklist/{id}` + bulk delete. Tests incl.
      remove-makes-grabbable-again (decision cache/spec level). [FRG-UI-017]

## 3. Command push gap (FRG-SCHED-010)

- [x] 3.1 Emit CommandStatusChanged on the started claim (commands/service.py
      _claim_next write session). Tagged WS test: queued→started→terminal all
      observable. Registry flip. [FRG-SCHED-010]

## 4. OPDS (FRG-OPDS-013, FRG-OPDS-007)

- [x] 4.1 `/opds/recent` acquisition feed (added_at desc, shared paging
      helpers) + root entry. Tests: newest-first by import time, full
      acquisition entries, page clamp. [FRG-OPDS-013]
- [x] 4.2 OpenSearch (a): root rel=search link, descriptor document, /opds/
      search?q= feed over series titles/aliases (bound params, folded match,
      length cap, escaping builder). Security tests: SQLi metachars, XML
      markup reflection, oversized input. Threat-model delta in the same
      change. [FRG-OPDS-007, FRG-PROC-006]

## 5. Delete-files wiring (FRG-API-003, FRG-UI-004)

- [x] 5.1 `DELETE /api/v1/issuefile/{id}` router → delete_issue_file (404 map;
      source=manual for the history event). Tests. [FRG-API-003, FRG-UI-004]
- [x] 5.2 delete_series(delete_files=True): files through recycle routing
      before row deletion (compensated); API 501 mapping removed. Tests: bin
      configured / not configured / mid-failure leaves rows intact.
      [FRG-API-003]

## 5b. Root-folder management (FRG-SER-008, FRG-UI-012)

- [x] 5b.1 `POST /api/v1/rootfolder` (absolute/exists/writable/no-nesting/no-dup
      validation, field-precise 400s) + `DELETE /api/v1/rootfolder/{id}`
      (409-class refusal while series reference it, 404 unknown). Tagged tests.
      [FRG-SER-008]
- [x] 5b.2 Media Management: Root Folders section (list + free space, add by
      path with API errors verbatim, guarded remove); Add Series and Library
      Import unconfigured states link to it. e2e run.sh drops the direct DB
      seed in favor of the API (proves first-run registration end-to-end).
      Vitest + e2e adjustments. [FRG-UI-012, FRG-SER-008]

## 6. Frontend (FRG-UI-010, FRG-UI-011, FRG-UI-017, FRG-UI-004)

- [x] 6.1 Shared usePagedQuery + page controls; History screen (Activity
      group): typed events, filters, expandable details w/ verbatim reasons.
      Vitest per delta scenarios. [FRG-UI-010]
- [x] 6.2 Wanted screen (top-level nav): rows w/ series links + per-issue
      automatic/interactive search, Search All (backlog-search command +
      status), explicit empty state. [FRG-UI-011]
- [x] 6.3 Blocklist screen (Activity group): reason cells verbatim, per-item +
      bulk remove w/ partial-failure reporting. [FRG-UI-017]
- [x] 6.4 SeriesDetail: per-issue delete-file action (confirmation names
      bin-vs-permanent), delete-files checkbox wired for real; invalidations
      (series, wanted, history). [FRG-UI-004]
- [x] 6.5 WS bridge branches + queryKeys for history/wanted/blocklist where
      backend events fire. [FRG-UI-010, FRG-UI-011, FRG-UI-017]

## 7. Docs, traceability, gate

- [x] 7.1 Manual: web-ui.md History/Wanted/Blocklist + SeriesDetail deletes;
      reading-opds.md Recent + search; import.md delete promise fulfilled;
      library.md 501 note replaced. [FRG-PROC-011]
- [x] 7.2 Security docs: OPDS search delta (untrusted query input); RISK-040
      disposition. [FRG-PROC-006]
- [x] 7.3 Registry flips (API-011, API-012, UI-010, UI-011, UI-017, SCHED-010,
      OPDS-007, OPDS-013) + matrix regen + soup 0. [FRG-PROC-004, FRG-PROC-005]
- [x] 7.4 e2e: run.sh now seeds the root folder through the real API
      (first-run registration proven end-to-end); full harness green on the
      assembled branch. The additional spine assertions (history shows the
      grab→import, wanted lists a missing issue, OPDS recent serves the file)
      are DEFERRED to the approved m2-search-autosuggest change — requirement
      evidence is complete via tagged backend/frontend tests. [FRG-PROC-010]
- [x] 7.5 Suites green; 8-angle + Codex gate; fixes; archive; --no-ff merge;
      main suites; tag v0.2.4. [FRG-PROC-007]
