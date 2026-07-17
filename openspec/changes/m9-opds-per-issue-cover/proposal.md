# m9-opds-per-issue-cover

## Approval

**Approved by Adrian, 2026-07-17 (in session, FRG-PROC-009):** reported live
during the Panels couch test — every issue of a series shows the same cover,
which also doesn't match the issue's first page — and approved for fix +
release. Registry ID FRG-OPDS-020.

## Why

When a series had a cached ComicVine cover, the acquisition feed advertised
that single volume image as the image/thumbnail for EVERY issue entry. In a
reader this made all issues of a series (e.g. the six Incal albums) render with
one identical cover, and that cover did not match the first page each issue
actually opens to. A comic's first page IS its cover, so the per-issue cover is
both distinct and correct — the volume image only makes sense once per series.

## What Changes

1. Issue (acquisition) entries advertise their OWN first-page cover render
   (`/opds/cover/{issue_file_id}`, already an OPDS-realm route, FRG-OPDS-011) —
   distinct per issue and matching what the reader opens.
2. The single series-level ComicVine cover moves to the series/shelf navigation
   entry (the All Series shelf and search results), where one cover per series
   is correct — and where nav entries previously carried no image at all. It is
   advertised only when a cover is actually cached.
3. `_issue_file_entry` no longer takes a series-cover URL.

## Impact

- Requirements: FRG-OPDS-020 (opds); MODIFIES the cover-link behavior described
  under FRG-OPDS-002/011 — restated in the delta.
- Code: `backend/src/foragerr/opds/router.py` only; no schema change.
- Tests: issue entries point at per-file cover (not the series URL); shelf nav
  entries carry the series cover when cached, none when not.
- Manual: `docs/manual/user/reading-opds.md` — clarify per-issue vs shelf cover.
- Security: none (same id-only cover routes). SOUP: none.
