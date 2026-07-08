## Why

M3 change 1 shipped the pull backbone; the weekly-pull screen (change 2) is parked
pending a design review. This change takes **M3 change 3 — OPDS page streaming**, the
other approved M3 cluster with no design dependency: the reading half.

Today (M1, FRG-OPDS-005) foragerr serves comics to an iPad reader over Tailscale as a
**whole-file download** — the reader pulls the entire `.cbz`/`.cbr` and pages through
it locally. That works, but PSE-capable readers (Panels, Chunky) can stream a comic
**page by page** via the OPDS Page Streaming Extension (OPDS-PSE 1.0), which is faster
to open, cheaper on a large issue, and the de-facto expectation of those readers. The
approved OPDS baseline (FRG-OPDS-008..012) is exactly this upgrade: a PSE stream link
+ endpoint, cached page counts, natural page ordering, locally-generated cover
fallback, and hard resource limits on the new server-side archive/image work.

The open question the baseline flagged — *do Panels/Chunky prefer PSE or whole-file?* —
does not need answering to proceed: PSE ships **alongside** the existing whole-file
acquisition link (both appear on every issue entry), so a reader picks whichever it
supports and nothing regresses. This change is the one new **server-side archive-open
and image-decode surface** reachable from the OPDS listener, so it carries a security
delta and a new image dependency.

## What Changes

- **OPDS-PSE page streaming (MODIFIED FRG-OPDS-008)** — every issue entry gains an
  OPDS-PSE 1.0 stream link (`rel="http://vaemendis.net/opds-pse/stream"`, namespace
  `http://vaemendis.net/opds-pse/ns`) carrying `{pageNumber}`/`{maxWidth}` URI-template
  placeholders and an accurate `pse:count`. A new stream endpoint returns a **single
  bounds-checked page image**, resolved by library id (reusing the FRG-OPDS-005
  path-confinement resolver, never a client-supplied path), with optional server-side
  downscaling to `maxWidth` and a correct image `Content-Type`. The existing whole-file
  download stays; PSE is additive.

- **Cached page counts (MODIFIED FRG-OPDS-009)** — a new nullable `page_count` column
  on `issue_files`, populated at import from the archive open that **already happens**
  in the pipeline (`inspect_archive().image_count`) — no extra archive I/O. Feed
  rendering reads the cached count (zero archive opens per render, preserving the M1
  "no archive I/O at feed time" invariant). A `NULL` count (legacy/scan-discovered rows,
  or an unlistable archive) is computed **lazily on first stream/feed access and written
  back**. The count invalidates when the file changes (the row is replaced on
  re-import; a size/mtime mismatch on lazy read forces a recompute).

- **Natural page ordering (MODIFIED FRG-OPDS-010)** — pages are the archive's image
  members (`jpg/jpeg/png/webp`) in **numeric-aware natural order** (`2.jpg` before
  `10.jpg` regardless of zero-padding), ignoring directories, non-image members, and
  `ComicInfo.xml`. The same ordering computes the count and resolves page indexes, so
  `pse:count` and stream indexes always agree.

- **Local cover + thumbnail fallback (MODIFIED FRG-OPDS-011)** — issue entries emit
  both `http://opds-spec.org/image` and `.../image/thumbnail` links; when an issue has
  no stored remote ComicVine cover, the server serves a **locally extracted first page**
  (resized and cached per issue-file, distinct from the per-series ComicVine cover
  cache), so no downloadable entry is cover-less and no thumbnail hotlinks a third-party
  host (no client egress to ComicVine's CDN).

- **Resource limits on archive/image handling (MODIFIED FRG-OPDS-012)** — the new
  archive-opening and image-scaling paths enforce **configurable** limits: max archive
  member count and per-page decompressed size (reusing the existing `ArchiveLimits`
  central-directory caps), an image **pixel-dimension cap checked before PIL decode**
  (decompression-bomb defense), and a **per-request time bound** — a request that
  exceeds any limit fails with a 4xx/5xx and a bounded log line, never memory/CPU
  exhaustion. A crafted zip-bomb or pixel-bomb in the library degrades safely.

## Capabilities

### Modified Capabilities

- `opds`: FRG-OPDS-008..012 elaborated from approved baseline acceptance to implemented,
  with scenario-level acceptance (PSE stream, cached counts, natural ordering, local
  cover fallback, resource limits) over the existing M1 OPDS catalog.

## Impact

- **Code**: backend only. `security/archives.py` gains an ordered image-member listing
  and a safe single-member reader (byte-cap-before-read, zip-slip re-check) plus a
  per-request `ArchiveLimits` override; a new image module (Pillow decode → downscale →
  encode, with pixel/time caps and first-page cover extraction) — the codebase has **no
  existing image processing**, so this is new. `opds/atom.py` adds the PSE namespace and
  a `pse:count` link attribute; `opds/router.py` adds the PSE stream endpoint and a
  per-issue-file cover endpoint and emits the new links on issue entries. A natural-sort
  key helper. New OPDS-PSE config keys on `config.py`.

- **DB**: one nullable additive column `issue_files.page_count` under a new forward-only
  migration `0012` (rides FRG-DB-002/008; no DB *requirement* change). The per-page
  index is **not** persisted — pages are addressed positionally from the freshly-listed
  sorted image members; only the count is cached.

- **Dependencies / SOUP** (FRG-PROC-012): **Pillow is added as a new runtime
  dependency** — `docs/security/soup-register.md` is updated in this change (name,
  version constraint, source, purpose = OPDS-PSE page decode/downscale + cover
  extraction, supporting reqs FRG-OPDS-008/011/012, license), and `tools/soup_check.py`
  is kept at exit 0. **`rarfile` is deliberately NOT added**: CBR page-streaming
  gracefully degrades (no PSE link, `page_count` NULL) while whole-file CBR download
  still works — avoiding a shell-out-to-`unrar` attack surface for a marginal reader
  gain.

- **Security docs** (FRG-PROC-006): **required.** This is a new server-side
  **archive-open + image-decode** surface reachable from the OPDS listener (untrusted
  archive/image bytes from library files). `docs/security/threat-model.md` COMP 3 (OPDS)
  gains a STRIDE note on the stream/cover endpoints (zip-bomb / pixel-bomb / truncated-
  image / zip-slip on member names / per-request DoS), covered by the FRG-OPDS-012
  limits; `docs/security/risk-register.md` records the archive/image-decode arm on the
  OPDS surface (mitigated by member/byte/pixel/time caps + zip-slip re-check + no
  `LOAD_TRUNCATED_IMAGES` on untrusted input). New risk id only if the Pillow decode
  surface is judged distinct from the existing archive-open risk (decided at proposal
  gate; default: extend the existing archive-handling risk with the OPDS arm).

- **Manual** (FRG-PROC-011): **user + admin.** `docs/manual/user/` gains a note that
  PSE-capable readers (Panels/Chunky) stream page-by-page while others download whole
  files (both work); `docs/manual/admin/configuration.md` documents the new OPDS-PSE
  resource-limit keys. README OPDS labelling updated if it enumerates OPDS features.

## Non-goals

- **No CBR page streaming in the default deployment.** Without `rarfile`+`unrar`, a
  `.cbr` has no listable members, so it gets no PSE link and `page_count` stays NULL;
  its whole-file download (FRG-OPDS-005) is unaffected. Adding optional CBR PSE is a
  later, separately-justified change.

- **No reading-state / mark-as-read.** PSE streams pages; tracking read position is a
  reader-side concern (and a deliberate M1 divergence from Mylar) — not added here.

- **No OPDS 2.0, no new feed shelves.** This change is PSE + covers + limits over the
  existing OPDS 1.2 catalog; Recent Additions (FRG-OPDS-013) and search already shipped.

- **No general image pipeline.** Pillow is introduced narrowly for OPDS page/cover
  decode+resize under strict caps; it is not wired into import, metadata, or the UI.

## Approval

Pre-approved under the standing M2/M3 FRG-PROC-009 grant (2026-07-06: "keep going with
m2/m3 and all their related changes"). On 2026-07-08 Adrian confirmed the grant and
directed taking **M3 change 3 (opds-page-streaming) next**, ahead of change 2
(pull-experience), because change 2's weekly-pull screen depends on a design review
(the `Foragerr.dc.html` mockup) he wants to do with Fable first, whereas change 3 has
no design dependency. Recorded per the standing-grant model used across M2/M3.
