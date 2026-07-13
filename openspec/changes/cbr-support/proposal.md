# cbr-support

## Why

69% of the owner's real library (366 of 527 files in the dogfood corpus) is CBR, and every one of them is unreadable in the primary iPad reading flow: the OPDS page-streaming layer is zip-only, so CBR entries carry no PSE link and Panels browns them out (the FRG-OPDS-008 "non-listable archive" degradation, working as spec'd — but now with a number attached). Mylar3, the tool foragerr replaces, streams CBR via `rarfile` and has for years; parity here gates daily usability.

## What Changes

Phased, per owner decision (2026-07-13):

- **Phase 1 — native CBR page streaming.** The archive layer gains a RAR backend: `rarfile` (ISC) over an `unrar` binary shipped in the Docker image (RARLAB freeware license — redistributable, non-OSI, disclosed verbatim in the SOUP register; `bsdtar`/libarchive documented as the OSI-clean fallback backend). CBR files become listable: page counts populate (FRG-OPDS-009's lazy write-back path picks up existing rows with no re-import), PSE links appear, Panels reads them. Files on disk are untouched. Includes the misnamed-archive fallback (a zip renamed `.cbr` — and the reverse — opens via content detection, a real-world class Mylar handles).
- **Phase 2 — opt-in CBR→CBZ format-shift at import** (adopts approved backlog requirement FRG-PP-018, pulled from milestone B into 0.9.x): convert-once at import as an explicit library policy under the format-preference direction, verified-before-discard semantics as already spec'd. Off by default — consistent with the naming-defaults non-destructive stance.
- **Security work in the same change** (FRG-PROC-006): RAR is a new parser over untrusted input. STRIDE analysis + risk register entries; the RAR path inherits the existing archive resource limits from the OPDS streaming work (bomb/oversize/member-count guards, single-page extraction budget), with rarfile's subprocess isolation noted (parsing happens in the `unrar` process, not in-process).

## Capabilities

### New Capabilities

(none — extends existing capabilities)

### Modified Capabilities

- `opds`: new FRG-OPDS-016 (RAR-backed archive listing/extraction for page streaming, incl. misnamed-archive fallback). FRG-OPDS-008/009 requirements are unchanged — RAR support satisfies their existing scenarios for a larger file class.
- `pp`: FRG-PP-018 (CBR→CBZ conversion) modified — opt-in policy framing under format preferences, milestone pulled B → 0.9.x, retagging scope deferred where it depends on META tagging.

## Impact

- **Code**: archive-open layer serving OPDS page streaming and import-time page counts (zip-only today); import pipeline conversion step (phase 2); Dockerfile (`unrar` binary).
- **Dependencies / SOUP** (FRG-PROC-012): add `rarfile` (ISC, Python) and `unrar` (RARLAB freeware, binary, **non-OSI** — license text recorded verbatim; linuxserver.io ecosystem precedent). soup-register updated in the same change; `tools/soup_check.py` green at the gate.
- **Security** (FRG-PROC-006): `docs/security/` STRIDE + risk register updated in the same change (untrusted RAR input; subprocess boundary; resource limits).
- **Manual** (FRG-PROC-011): `docs/manual/user/` reading/OPDS section (CBR now streams; PDF remains download-only — Panels reads downloaded PDFs; opt-in PDF→CBZ deferred to the format-preferences change with `pypdfium2` (BSD) as the named candidate), admin configuration (conversion policy, backend selection).
- **Registry** (FRG-PROC-002): allocate FRG-OPDS-016; FRG-PP-018 milestone B → 0.9.x.
- **Test corpus**: 366 real `.cbr` files in `sample-comics/` (gated live-ish fixture; synthetic rar fixtures for CI).

## Approval

Approved — Adrian, 2026-07-13 (in-session, alongside naming-defaults; both queued as the next development).
