# cbr-support — tasks

## 1. Registry, SOUP, security (change-wide prerequisites)

- [x] 1.1 Registry: allocate FRG-OPDS-016 (proposed, 0.9.x); update FRG-PP-018 milestone B → 0.9.x
- [x] 1.2 SOUP register: add `rarfile` (ISC) and `unrar` binary (RARLAB freeware license verbatim, non-OSI flagged, subprocess-boundary note, libarchive fallback documented); tools/soup_check.py green
- [x] 1.3 Security docs (FRG-PROC-006): STRIDE entries + risk register for untrusted RAR input (subprocess isolation, resource limits, encrypted/solid archive handling); note the misnamed-archive content-sniff in the parser surface inventory
- [x] 1.4 Dockerfile: install `unrar` (linuxserver convention); build note for the libarchive fallback

## 2. Phase 1 — archive opener seam + RAR backend

- [x] 2.1 Refactor the zip-only archive open path into a single dispatcher seam (extension first, content-sniff fallback both directions); no behavior change for zip (FRG-OPDS-008/009/010 tests stay green untouched)
- [x] 2.2 Add the rarfile backend behind the seam: listing, natural ordering, single-member streaming reads; same member-count/size/decode limits as zip
- [x] 2.3 Test (FRG-OPDS-016): CBR fixture streams page-by-page — PSE link, accurate pse:count, in-range/out-of-range, width cap — mirroring the CBZ test matrix
- [x] 2.4 Test (FRG-OPDS-016): pre-existing CBR row with NULL page_count heals lazily on first stream and renders PSE with zero archive I/O afterwards
- [x] 2.5 Test (FRG-OPDS-016): zip-renamed-.cbr and rar-renamed-.cbz open by content detection
- [x] 2.6 Test (FRG-OPDS-016): backend missing/failing → download-only entry, stream 404, no error feed; encrypted-rar fixture degrades the same way
- [x] 2.7 Test (FRG-OPDS-016): oversized/bomb rar fixtures refused within the limit framework
- [x] 2.8 Gated corpus run (not CI): stream-check across sample-comics' 366 .cbr files; record pass rate + failure classes in the change notes; re-verify the libarchive fallback claim on the same corpus

## 3. Phase 2 — opt-in convert-at-import (FRG-PP-018)

- [ ] 3.1 Conversion step in the import pipeline behind the off-by-default policy flag (surfaced with format-preference config); verify-before-discard (member count + final-member decode); atomic issue_files swap; history event
- [ ] 3.2 On-demand convert commands per issue and per series (skip non-CBR as no-ops)
- [ ] 3.3 Test (FRG-PP-018): enabled-policy import converts + verifies + swaps + records; default import leaves .cbr byte-identical
- [ ] 3.4 Test (FRG-PP-018): failed verification keeps the original and the import still succeeds
- [ ] 3.5 Test (FRG-PP-018): per-series on-demand conversion under verify-before-discard

## 4. Docs, gate, and merge

- [ ] 4.1 Manual: user reading/OPDS section (CBR streams now; PDF = download-only, Panels reads it; pdf→cbz deferred to format-preferences) + admin configuration (policy flag, backend selection/fallback)
- [ ] 4.2 Regenerate traceability matrix
- [ ] 4.3 Full suite green; security-touching change → full 8-angle review gate + Codex (per tiered-gates standard, new parser surface); merge --no-ff; delete branch
