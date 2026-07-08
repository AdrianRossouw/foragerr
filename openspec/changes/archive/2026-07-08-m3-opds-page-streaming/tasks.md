Work areas partitioned by file ownership so each runs in its own worktree
(FRG-PROC-008), one writer per file area. Shared files — `importer/pipeline.py` and
`config.py` (area C) and the requirements registry (area D) — are the only cross-area
contention points; the orchestrator owns those merges. Every requirement gets at least
one tagged test (FRG-PROC-004): pytest `@pytest.mark.req("FRG-OPDS-...")`.

**Ordering / dependencies:** A defines the archive/image core (member listing, safe
reader, decode/downscale/cover under caps) that B and C code against, so A lands (or
its signatures freeze) first; B and C then proceed in parallel; D closes the gate.

## A. Backend — archive/image core (FRG-OPDS-010, FRG-OPDS-012)

*Subtlety: HIGH — the resource caps and the natural-order/image-only member selection
are the security-and-correctness core.* Owns: `security/archives.py` (additive), a new
image module (`opds/images.py` or `security/images.py`), a natural-sort helper.

- [x] A.1 Ordered image-member listing: given a confined archive path + `ArchiveLimits`,
      return the image members (jpg/jpeg/png/webp) in numeric-aware natural order,
      excluding dirs/symlinks/non-images/`ComicInfo.xml`; gate on `safe_to_extract`.
      Reuse `_IMAGE_EXTS` and `is_safe_member_name`. Tagged tests: `1,2,10.jpg` →
      indexes 0..2; `ComicInfo.xml`/dir ignored; count == len(list). [FRG-OPDS-010]
- [x] A.2 Safe single-member reader: byte-cap-BEFORE-read (member.file_size vs cap),
      re-check `is_safe_member_name`, catch `(OSError,BadZipFile,NotImplementedError,
      zlib.error)` → bounded failure. Tagged tests: over-cap member refused pre-read;
      traversal member name rejected. [FRG-OPDS-012]
- [x] A.3 Image decode/downscale/encode + first-page cover extraction (Pillow): lazy
      `Image.open` header read → pixel-cap check BEFORE `load()` (no
      `LOAD_TRUNCATED_IMAGES`), downscale to `maxWidth` (aspect preserved, never
      upscale), per-request time bound; extract+resize page 0 for a cover. Tagged
      tests: `width` yields image no wider than requested; over-pixel image refused
      pre-decode; truncated/garbage bytes → bounded failure. [FRG-OPDS-012, FRG-OPDS-008]

## B. Backend/OPDS — serving + emission (FRG-OPDS-008, FRG-OPDS-011)

*Subtlety: MEDIUM — endpoint wiring + the link/template emission; the confinement
resolver is reused verbatim.* Owns: `opds/router.py`, `opds/atom.py`. Depends on A.

- [x] B.1 PSE stream endpoint `GET {base}/page/{issue_file_id}/{pageNumber}?width=`:
      resolve by id via `validate_under_root` (as `download_file` does), list members
      (A.1), bounds-check `pageNumber`, read (A.2) + decode/downscale (A.3), return
      `image/*`. Out-of-range/negative → 404; non-listable archive → 404. Tagged tests:
      in-range page streams; out-of-range 4xx; width bound; id-only resolution (no path
      field). [FRG-OPDS-008]
- [x] B.2 Local cover endpoint `GET {base}/cover/{issue_file_id}` (+`?thumbnail`):
      first-page cover extracted/resized/cached under `<config>/covers/pages/<id>.jpg`
      (existence-keyed), served `FileResponse`; used as fallback when no remote cover.
      Tagged tests: cover-less issue gets a local cover, thumbnail served locally (no
      external host). [FRG-OPDS-011]
- [x] B.3 Emission: declare `xmlns:pse` on the feed; extend atom `Link` with a
      `count`/attrs mechanism and teach `_link_el` to emit `pse:count`; in
      `_issue_file_entry` emit the PSE stream link (literal `{pageNumber}`/`{maxWidth}`,
      `pse:count` from the cached count) ONLY when listable, plus image/thumbnail links
      pointing at the local cover endpoint when no remote cover. Tagged tests: entry has
      PSE link + count for a listable file and none for a non-listable one; image links
      present. [FRG-OPDS-008, FRG-OPDS-011]

## C. Backend — page-count persistence + import producer + config (FRG-OPDS-009)

*Subtlety: MEDIUM — the cache/invalidation and the no-extra-open producer.* Owns:
`library/models.py` (column), migration `0012`, `importer/pipeline.py` (shared —
orchestrator merges), `config.py` (shared — orchestrator merges).

- [x] C.1 `issue_files.page_count` nullable column + forward-only migration `0012`
      (down_revision `0011_pull_entries`, `downgrade` raises). Populate at import from
      `report.image_count` when `report.listed` (no extra archive open), else NULL, at
      the `IssueFileRow` creation site in the execute path. Tagged tests: imported CBZ
      row has count == image_count; unlistable → NULL; schema round-trip. [FRG-OPDS-009]
- [x] C.2 Lazy first-access compute + write-back + size-mismatch invalidation (a small
      service used by B's endpoints and the feed count read): NULL → compute from
      members (A.1) and persist; stored `size` != on-disk size → recompute. Tagged
      tests: NULL count computed + written on first access; feed render opens no archive
      when count present; size change forces recompute. [FRG-OPDS-009]
- [x] C.3 Config keys `opds_pse_max_members`, `opds_pse_max_page_bytes`,
      `opds_pse_max_pixels`, `opds_pse_request_timeout_seconds`, `opds_pse_max_width`
      (pydantic `Field` + clamp where a hard floor matters), folded into a per-request
      `ArchiveLimits` override. Tagged test: out-of-range value clamped with a warning.
      [FRG-OPDS-012]

## D. Docs, security, SOUP, traceability, gate

*Subtlety: security judgment (the new decode surface) is non-mechanical.* Owns:
`docs/`, `soup-register.md`, registry, matrix.

- [x] D.1 SOUP (FRG-PROC-012): add **Pillow** to `docs/security/soup-register.md`
      (runtime; version constraint, source, purpose = OPDS-PSE decode/downscale + cover
      extraction, supporting reqs FRG-OPDS-008/011/012, license); keep
      `tools/soup_check.py` at exit 0. Confirm `rarfile` is NOT added. [FRG-PROC-012]
- [x] D.2 Security (FRG-PROC-006): `docs/security/threat-model.md` COMP 3 (OPDS) gains a
      STRIDE note on the stream/cover endpoints (zip-bomb/pixel-bomb/truncated-image/
      zip-slip-on-member/per-request DoS) covered by FRG-OPDS-012; `risk-register.md`
      records the OPDS archive/image-decode arm (default: extend the existing
      archive-handling risk with the OPDS arm; new RISK id only if judged distinct).
      [FRG-PROC-006]
- [x] D.3 Manual (FRG-PROC-011): `docs/manual/user/` note that PSE readers (Panels/
      Chunky) stream page-by-page while others download whole files (both work);
      `docs/manual/admin/configuration.md` documents the new OPDS-PSE keys. README OPDS
      labelling if it enumerates features. [FRG-PROC-011]
- [x] D.4 Registry + matrix: FRG-OPDS-008..012 flip `approved → implemented`;
      traceability matrix regenerated; `tools/trace.py` exit 0. [FRG-PROC-004, FRG-PROC-005]
- [x] D.5 Gate: backend suite green; pre-merge review cycle (8 Claude angles + Codex) on
      the branch diff; fixes; archive; `--no-ff` merge with full suite green; CHANGELOG
      v0.3.1 entry + `pyproject` bump + post-merge SemVer tag v0.3.1 + GitHub Release per
      FRG-PROC-013. [FRG-PROC-007, FRG-PROC-013]
