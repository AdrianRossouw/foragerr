# m9-ux-diagnosability — tasks

## 1. Guidance + navigation (FRG-UI-033, FRG-UI-034, FRG-UI-036)

- [x] 1.1 Linkify the ComicVine-key guidance (Add New + library-import picker share the string) → Settings → General; add-dialog root-folder notice → Media Management (kept as fallback wording alongside 1.2)
- [x] 1.2 Add dialog: inline root-folder registration when none exist (path input + register via POST /api/v1/rootfolder; success proceeds in-dialog, refusal shown verbatim)
- [x] 1.3 Router: catch-all not-found route inside the shell with a library link
- [x] 1.4 Pull-source health remediation copy: UI terms (and any other config-key mention in UI-facing warning strings)
- [x] 1.5 Tests (vitest, tagged): link navigation, inline-register flow + refusal, not-found render, copy assertions

## 2. Calendar (FRG-UI-035)

- [x] 2.1 Calendar reads pull-source health; inline degraded notice; nothing when healthy or pull disabled
- [x] 2.2 Tests (vitest + pytest as fits, tagged)

## 3. Queue awaiting-import (FRG-UI-037)

- [x] 3.1 Queue surfaces completed-but-unimported tracked downloads with an awaiting-import status (backend queue resource already tracks state — extend serialization/UI as needed, no schema change expected)
- [x] 3.2 Tests (tagged)

## 4. OPDS (FRG-OPDS-017, FRG-OPDS-018)

- [x] 4.1 HEAD on feed/file/page routes (same auth challenge + headers, no body)
- [x] 4.2 File-less series omitted from series feeds; config `opds_hide_fileless_series` (default true); manual + config docs
- [x] 4.3 Tests (pytest, tagged): HEAD parity incl. 401 challenge; shelf filtering + opt-out

## 5. Log parity (FRG-NFR-016)

- [x] 5.1 Library-import execute: WARNING per failed/blocked group with verbatim reason
- [x] 5.2 Test (pytest, tagged)

## 6. Docs, gate, merge

- [x] 6.1 Manual: web-ui.md (calendar notice, queue states, not-found), reading-opds.md (HEAD, empty shelves), configuration.md (new OPDS setting row; read-only root folders documented as unsupported — F14 owner default)
- [ ] 6.2 Suites + tsc green; matrix regen; soup/risk exit 0
- [ ] 6.3 Tiered gate (medium: 4-5 angles + Codex — broad UI surface); registry flip; archive; merge --no-ff; /release v0.9.13
