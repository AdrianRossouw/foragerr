# activity-hygiene — tasks

## 1. Backend bulk remove (FRG-DL-008)

- [ ] 1.1 POST /queue/remove {ids, blocklist, deleteData} looping the
      single-remove semantics per row; per-row 409-on-importing into the
      errors map; blocklist via the shared writer; best-effort client
      removal; applied/errors result shape
- [ ] 1.2 Tests: mixed batch (one importing → per-row error, rest
      removed), blocklist rows written, client-removal failure never
      blocks de-tracking; tags FRG-DL-008

## 2. Queue screen (FRG-UI-006)

- [ ] 2.1 Compose components/dataTable.module.css; tableWrap scroll
      container; wrap release tokens; fix the flex-on-td actions cell;
      no page-level horizontal scroll
- [ ] 2.2 Failed rows: no progress bar/byte counts; status+reason carry
      it; series/issue still identify hash-titled rows
- [ ] 2.3 Selection column + select-all (Blocklist pattern), bulk Remove
      via the existing dialog, Clear failed (select+confirm+bulk),
      PageControls paging
- [ ] 2.4 Vitest: overflow containment (class/structure), failed-row
      presentation, selection + bulk + clear-failed against a mocked
      bulk endpoint incl. per-row failure surfacing, paging; FRG-UI-006
      in names

## 3. Docs + verification

- [ ] 3.1 docs/manual/user/web-ui.md queue section
- [ ] 3.2 Suites green (backend xdist, frontend serialized), tools exit
      0, e2e green, live-rig verification (the real 10-row queue)
