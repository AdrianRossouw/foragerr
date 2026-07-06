## 1. Backend — ComicVine client auth carve-out (FRG-META-004)

- [ ] 1.1 In `metadata/comicvine.py::_paginate`, re-raise `ComicVineAuthError`
      ahead of the general `ComicVineError` degrade path; verify the raised
      message never contains the API key. [FRG-META-004]
- [ ] 1.2 Survey `_paginate` callers (search, refresh/sync flows): confirm each
      boundary already catches `ComicVineError` (parent of auth) and now fails
      loudly instead of recording an incomplete sync; add/adjust one refresh-path
      test with an auth failure. [FRG-META-004]
- [ ] 1.3 Tests tagged `@pytest.mark.req("FRG-META-004")`: auth failure on page 1
      and mid-walk both raise; non-auth mid-walk failure still degrades to
      `complete=False` partials. [FRG-META-004]

## 2. Backend — lookup endpoint outcome classes (FRG-API-003)

- [ ] 2.1 Replace `lookup_series` response with a
      `LookupResponse { records, complete }` envelope carrying the walk's
      `complete` flag. [FRG-API-003]
- [ ] 2.2 Map `ComicVineAuthError` to `_COMICVINE_LOOKUP_ERROR_STATUS` (503)
      with a static message naming the ComicVine API key as the cause (no key
      material interpolated); keep the general `ComicVineError` backstop.
      [FRG-API-003]
- [ ] 2.3 Tests tagged `@pytest.mark.req("FRG-API-003")`: auth failure → 503
      with credential-naming message (assert exact message text, assert key
      absent); degraded walk → 200 envelope `complete=false`; clean empty →
      200 `complete=true, records=[]`. [FRG-API-003]

## 3. Frontend — Add Series outcome states (FRG-UI-005)

- [ ] 3.1 Update `api/hooks.ts::useLookup` (and types) to the envelope shape;
      surface the API error message/status on the query error object.
      [FRG-UI-005]
- [ ] 3.2 In `screens/add/AddSeries.tsx`, branch: credential-failure error
      state ("ComicVine API key missing or invalid — check Settings"), generic
      lookup error, incomplete-results notice alongside candidates, and plain
      "no results" only for complete-and-empty; isolate the credential-error
      detection in one tested helper. [FRG-UI-005]
- [ ] 3.3 Vitest tests with FRG-UI-005 in the name: credential error renders
      Settings guidance; incomplete renders notice + candidates; complete-empty
      renders "No volumes found". [FRG-UI-005]

## 4. Docs, traceability, merge gate

- [ ] 4.1 Manual (FRG-PROC-011): troubleshooting entry "series search returns
      nothing" (key unset/invalid, where to set it); Add Series section notes
      the error/incomplete states. [FRG-PROC-011]
- [ ] 4.2 Traceability: regen matrix; registry rows FRG-META-004/API-003/UI-005
      unchanged in status (already implemented — amended behavior), verify tags
      resolve; `tools/soup_check.py` exits 0 (no dependency changes).
      [FRG-PROC-004, FRG-PROC-005]
- [ ] 4.3 Full backend + frontend suites green on the change branch; pre-merge
      review cycle (/code-review + /simplify); archive change; `--no-ff` merge;
      suites on main. [FRG-PROC-007]
