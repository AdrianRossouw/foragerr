# m9-opds-cover-realm

## Approval

**Approved by Adrian, 2026-07-17 (in session, FRG-PROC-009):** found live
during the M9 Panels couch test — covers never load in the reader — and
approved for fix + release on the spot ("fix it now… actually, do release
it"). Registry ID FRG-OPDS-019.

## Why

An OPDS reader (Panels, verified on-device) authenticates against the OPDS
Basic realm (`FRG-AUTH-005`, realm `foragerr-opds`), which covers `/opds/*`
only. But the acquisition feed advertised each entry's image/thumbnail link as
`/api/v1/series/{id}/cover` — a route behind the web-UI/API-key perimeter, NOT
the OPDS realm. The reader's Basic credentials are rejected there (401), so
**every cover for a series with a cached ComicVine cover fails to load** in any
OPDS client. The title-page fallback (`FRG-OPDS-011`, for series with no remote
cover) was already correctly on the OPDS realm; only the remote-cover branch
pointed at `/api`.

The sim run and the e2e OPDS test both missed it because they fetched cover
URLs directly rather than *following the feed's advertised image link under
Basic auth* — a coverage gap this change closes with a link-following test.

## What Changes

1. New OPDS-realm route `GET /opds/series-cover/{series_id}` serving the cached
   series cover from disk (`<config>/covers/<id>.jpg`; 404 when absent) — the
   same bytes as the API route, under OPDS Basic auth, with HEAD parity
   (`FRG-OPDS-017`). `series_id` is an int, so the path has no
   request-controlled component (`FRG-OPDS-004` posture preserved).
2. The feed's image/thumbnail links point at this OPDS-realm route instead of
   `/api/v1/series/{id}/cover`.
3. Test that FOLLOWS the advertised image link under Basic auth and asserts it
   serves image bytes (the assertion the prior tests lacked), plus HEAD parity
   and the 404 path.

## Impact

- Requirements: FRG-OPDS-019 (opds).
- Code: `backend/src/foragerr/opds/router.py` (new route + `_cover_url`);
  no schema change; the `/api` route is unchanged (still serves the web UI).
- Tests: opds cover-realm test (follow-the-link + HEAD + 404).
- Manual: `docs/manual/user/reading-opds.md` — covers now load in readers
  (was implicitly claimed; now true). No new user-facing setting.
- Security: no new attack surface — id-only, root-fixed path, same confinement
  posture as the existing cover routes; STRIDE unchanged. SOUP: none.
