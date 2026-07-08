# Design: m3-opds-page-streaming (M3 change 3)

Implements FRG-OPDS-008..012 over the M1 OPDS 1.2 catalog. The guiding constraints
are the two M1 OPDS invariants — **zero archive I/O at feed render** and **library-id-
only file resolution (no client-supplied paths)** — plus the project rule that new
untrusted-parser surface is spec'd for security (FRG-PROC-006).

## 1. PSE alongside whole-file (resolves the baseline open question)

Every issue-file entry carries BOTH the M1 whole-file acquisition link (FRG-OPDS-005)
AND the new PSE stream link (FRG-OPDS-008). A reader uses whichever it supports; a
non-PSE reader ignores the PSE link. So "do Panels/Chunky prefer PSE?" needs no
answer before shipping — nothing regresses, PSE is strictly additive. (If a future
live test shows a reader mishandles a dual-link entry, that is a follow-up.)

## 2. Page model — count cached, index computed (D9/D10)

A "page" is an archive member whose extension is in the existing image set
(`security/archives.py:_IMAGE_EXTS` — jpg/jpeg/png/webp), excluding directories,
symlink members, `ComicInfo.xml`, and non-images. Pages are ordered by a **natural
(numeric-aware) key** on the member name, so `1.jpg, 2.jpg, 10.jpg` → indexes 0,1,2.

- **Count** (`pse:count`) is **cached** on `issue_files.page_count` (nullable). The
  same natural ordering that lists pages produces the count, so count and indexes can
  never disagree.
- **The per-page index is NOT persisted.** At stream time the endpoint re-lists the
  archive's image members (a central-directory read, no decompression), natural-sorts
  them, and picks member `[pageNumber]`. Persisting the name list buys nothing over a
  cheap re-list and would be a second thing to invalidate.

### Where the count comes from (no extra archive open — D9)

The import pipeline already opens each archive once (`importer/pipeline.py` →
`inspect_archive`), and `ArchiveReport.image_count` is exactly the page count for a
**listed** archive (CBZ, or CBR when `rarfile` is present). So the producer is: at
issue-file creation in the execute path, set `page_count = report.image_count` when
`report.listed`, else `NULL`. No new archive open at import.

- **First-access fallback:** a `NULL` page_count (legacy rows, scan-discovered rows,
  or an archive that was unlistable at import) is computed lazily on the first
  stream/feed access from the freshly-listed members and written back — the same
  "NULL means compute from the file" convention `fix_revision` already uses.
- **Invalidation:** a re-import replaces the `issue_files` row (fresh count). For the
  lazy path, the stored `size` is checked against the file's current size before
  trusting a cached count; a mismatch forces a recompute (cheap file-change guard
  without a content hash).

## 3. Stream + cover endpoints — reuse the M1 resolver (D8, security)

New routes in `opds/router.py`, both resolving **by library id exactly like
`download_file`**: `session.get(IssueFileRow, id)` → `validate_under_root(row.path,
roots)` (`security/paths.py`) → `is_file()`; any failure → 404. No client-supplied
path ever touches the filesystem (FRG-OPDS-003 by construction, unchanged).

- `GET {base}/page/{issue_file_id}/{pageNumber}?width=` → the single decoded page
  image (optionally downscaled to `width`), `Content-Type: image/*`. Out-of-range
  `pageNumber` → 404; a non-listable archive → 404 (the entry carries no PSE link
  anyway).
- `GET {base}/cover/{issue_file_id}` (+ `?thumbnail`) → the local first-page cover
  (extracted, resized, cached under `<config>/covers/pages/<issue_file_id>.jpg`),
  used only as the fallback when the issue has no remote ComicVine cover (FRG-OPDS-011).
  Per-issue-file key space — deliberately separate from the per-**series** ComicVine
  cover cache (`<config>/covers/<series_id>.jpg`), which is untouched.

The PSE link href template is emitted as `{base}/page/{issue_file_id}/{pageNumber}`
with literal `{pageNumber}`/`{maxWidth}` braces (they pass through the atom escaper
unescaped) and a `pse:count="N"` attribute — requiring a new namespace decl on the
`<feed>` element and a `count` field on the atom `Link` dataclass.

## 4. Image handling + resource limits (D12, security) — the new attack surface

The codebase has **no image library**; this change adds **Pillow** (narrowly, for OPDS
only). The single new `opds/images.py` (or `security/images.py`) module owns every
decode, under layered caps so untrusted archive/image bytes cannot exhaust the box:

1. **Member/byte caps** — reuse `ArchiveLimits` (max members, per-member declared
   size) on the central directory *before* any read; a member whose declared size
   exceeds `opds_pse_max_page_bytes` is refused pre-decompression (zip-bomb defense
   already modeled). Re-check `is_safe_member_name` on the chosen member (zip-slip).
2. **Read cap** — copy the `comicinfo.read_embedded_metadata` idiom: check
   `member.file_size > cap` BEFORE `archive.read(name)`; catch
   `(OSError, BadZipFile, NotImplementedError, zlib.error)` → bounded failure.
3. **Pixel cap before decode** — set `Image.MAX_IMAGE_PIXELS` and, after a lazy
   `Image.open()` (which reads only the header), reject `img.size[0]*img.size[1] >
   opds_pse_max_pixels` BEFORE `img.load()`/resize — the decompression-bomb guard. Do
   **not** enable `LOAD_TRUNCATED_IMAGES` on this untrusted path.
4. **Per-request time bound** — wrap the decode+resize in a bounded operation
   (`opds_pse_request_timeout_seconds`); over-budget → 5xx + log, never an unbounded
   spin. Runs on the FS-offload thread seam so a wedged decode never blocks the loop.

Config keys (pydantic `Field` + the `_clamp_intervals`-style clamp where a hard floor
matters): `opds_pse_max_members`, `opds_pse_max_page_bytes`, `opds_pse_max_pixels`,
`opds_pse_request_timeout_seconds`, `opds_pse_max_width`. Most fold straight into a
per-request `ArchiveLimits(...)` override rather than the shared default.

## 5. CBR degradation (non-goal made explicit)

`rarfile` is not a dependency and shells out to `unrar` — deliberately excluded. A
`.cbr` therefore has `report.listed=False`/`safe_to_extract=False`: no PSE link,
`page_count` NULL, no local cover extraction. Its whole-file download (FRG-OPDS-005)
and any remote ComicVine cover are unaffected. Gate any page/cover extraction on
`report.safe_to_extract`, never `report.ok` (the archive module's documented rule).

## 6. Work-area partition (FRG-PROC-008, one writer per file area)

- **A — archive/image core** (`security/archives.py` extension + new image module +
  natural-sort helper). Foundation: ordered image-member listing, safe single-member
  reader, Pillow decode/downscale/encode + cover extraction under all caps. B and C
  code against its interface, so A lands (or its signatures freeze) first. HIGH
  subtlety (the security caps are the correctness core).
- **B — OPDS serving + emission** (`opds/router.py` + `opds/atom.py`). Owns all of
  `opds/`: the stream + cover endpoints and the PSE/image link emission. Depends on A.
- **C — DB + import producer + config** (`library/models.py` column + migration 0012 +
  `importer/pipeline.py` page_count set + `config.py` keys). Depends on A's report
  fields (already present). Import-pipeline is a shared file — orchestrator merges.
- **D — docs/security/SOUP/traceability/gate.** Pillow SOUP row, threat-model COMP 3
  note + risk arm, registry flip + matrix, manual (user + admin).

Contention points the orchestrator owns: `config.py` (C only here), `importer/
pipeline.py` (C only), the requirements registry (D). `opds/` is B-only; the archive/
image core is A-only.

## 7. Testing (FRG-PROC-004)

Real CBZ bytes (reuse `tests/importer/_archives.py` zip builders — `opds_support.seed`
currently writes arbitrary bytes, insufficient for PSE). Tagged tests per requirement:
natural order `1,2,10` → indexes 0..2 and a `ComicInfo.xml` member does not shift
numbering (010); out-of-range page → 4xx, `width` returns an image no wider than asked
(008); second feed render does zero archive opens, file replace updates count (009);
cover-less issue still shows a cover with no internet egress, thumbnail served locally
(011); zip-bomb / pixel-bomb / oversized-member CBZ → bounded logged failure, limits
configurable (012). Security cases live in `test_opds_security.py`.

## Open Questions

None blocking. Implementation-time calls, each with a default:

1. **New risk id vs extend existing** — the OPDS archive/image-decode arm is likely an
   extension of the existing archive-handling risk (import already opens archives);
   default is to add the OPDS arm to that row, allocate a new RISK id only if the
   Pillow decode surface is judged materially distinct. *Decided in area D.*
2. **Cover-cache column** — whether to add `issue_files.cover_extracted_at` or rely on
   file existence under `covers/pages/`. Default: **file existence** (simplest; a
   re-import replaces the row and a stale cover is harmless/overwritten), no extra
   column beyond `page_count`.
3. **Downscale filter/encode** — default: Pillow `thumbnail()` with Lanczos, re-encode
   to JPEG for photographic pages; preserve PNG for PNG sources only if a reader needs
   alpha (unlikely for comics). Tune if quality is poor on a real device.
