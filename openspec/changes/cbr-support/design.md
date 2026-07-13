# cbr-support — design

## Context

The archive layer behind OPDS page streaming (FRG-OPDS-008/009/010) is deliberately zip-only: `zipfile` + Pillow with resource limits, chosen in M3 to avoid a RAR dependency. The spec anticipated the gap — "an entry whose archive is not listable (e.g. a CBR with no unrar support) SHALL carry no PSE link" — and the dogfood corpus quantified it: 69% CBR. Mylar3 (reference in `.reference/mylar3`) streams CBR with `rarfile.RarFile` behind the same page-serving code path as `zipfile.ZipFile`, including a fallback for zips renamed `.cbr` (`getimage.py:open_archive`).

## Goals / Non-Goals

**Goals:**
- CBR parity with CBZ across page streaming, page counts, and cover extraction — no file rewriting required (phase 1).
- Opt-in convert-at-import policy for operators who want a uniform zip library (phase 2, FRG-PP-018 semantics).
- License posture stated plainly: what ships, under what license, disclosed where.
- No weakening of the existing archive resource-limit and confinement posture.

**Non-Goals:**
- PDF page streaming or PDF→CBZ conversion (deferred to the format-preferences change; `pypdfium2`, BSD, is the named rasterizer candidate — MuPDF is AGPL and rejected).
- RAR *creation* (never needed; also the one thing the unrar license forbids deriving).
- Library-wide retagging (the META-dependent half of FRG-PP-018's original text — stays backlogged with META).
- Solid-archive optimization: rare for comics; first version accepts slower extraction on solid archives.

## Decisions

1. **Backend: `rarfile` (ISC) + `unrar` binary, subprocess boundary.** Best-compatibility path (RAR4+RAR5), production-proven by Mylar3 and the SABnzbd ecosystem; linuxserver.io images already ship `unrar`, matching the deployment convention. The subprocess boundary means no license contamination of foragerr code and no in-process parsing of untrusted RAR structures. `bsdtar`/libarchive (BSD-2, independent RAR readers) is the documented OSI-clean fallback backend — `rarfile` supports it natively — with the caveat of known gaps on some archives; the 366-file corpus is the acceptance bar for backend claims.
2. **License handling.** `unrar` is RARLAB freeware: free use and redistribution, non-OSI (Debian non-free), with the sole restriction that its source must not be used to create a RAR-compatible archiver (we only extract). SOUP register carries the license verbatim and flags non-OSI status explicitly; the Dockerfile installs the binary at image build; nothing unrar-derived enters the repo.
3. **One archive-opener seam.** The existing zip-only open path becomes a small dispatcher: try by extension, fall back by content sniffing (zip magic in a `.cbr` and vice versa — the Mylar lesson). Everything downstream (natural ordering FRG-OPDS-010, page-count cache FRG-OPDS-009, width-capped page serving FRG-OPDS-008) is format-agnostic already and must not change.
4. **Existing rows heal without re-import.** CBR `issue_files` rows have `page_count NULL`; FRG-OPDS-009's lazy compute-and-write-back populates them on first stream, and feed rendering then emits PSE links. No migration, no rescan required. (A bulk "warm page counts" command is a nice-to-have task, not a requirement.)
5. **Resource limits carry over.** The RAR path enforces the same guards as zip: member-count and per-member size ceilings, image decode limits (Pillow confinement from M3), extraction via streaming single-member reads (`unrar p`-equivalent through rarfile), never full-archive extraction to disk. Missing/broken `unrar` at runtime degrades to exactly today's behavior (no PSE link, download-only) — never an error page.
6. **Phase 2 rides the existing FRG-PP-018 contract**: convert at import, verify the produced CBZ (member count + readable last page) before discarding the original, off by default, policy surfaced under format preferences. Retag half deferred (Non-Goals).

## Risks / Trade-offs

- **Non-OSI binary in the image**: acceptable for a self-hosted single-operator tool; disclosed in SOUP; OSI-clean fallback documented. The *repo* stays clean — the binary is an image build artifact.
- **Subprocess-per-page overhead**: rarfile spawns unrar per read; with the existing render semaphore and page-count cache this is acceptable for single-operator load (Mylar precedent). Revisit only if dogfooding shows latency pain (then: per-file page cache already exists to amortize).
- **Solid/encrypted archives**: extraction may be slow (solid) or fail (encrypted) — both degrade per FRG-OPDS-008's non-listable path and are logged; corpus will show prevalence (expected ≈0 for comics).
- **Phase-2 conversion rewrites files** — tension with the non-destructive stance; resolved by being opt-in, off by default, verified-before-discard, and recorded in history events.
