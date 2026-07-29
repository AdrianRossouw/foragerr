# m11-discovery-surface — the Calendar earns its keep

## Why

The Calendar is a discovery surface the operator cannot act on and can
barely read. Rig finding #17: the add affordance exists only inside the
"New this week" strip, gated to issue #1/#0 debuts — the other 76
unmatched books of a real week are unclickable by design, and the
separate strip itself read as a confusing second stack. Meanwhile the
pull source's payload already carries cover art, creators, characters,
description, and UPC for every entry — verified live 2026-07-29: 72/72
entries with covers, 66/72 with descriptions — and the ingest drops all
of it, leaving the Calendar a wall of text while budget-free imagery
sits unfetched. Serving those covers means the cover proxy's allowlist
grows by the LOCG image host, which makes this the milestone's one
security-touching change (FRG-PROC-006 applies in full).

## What Changes

- **Add from anywhere, CV-id-first** (MODIFIED `FRG-PULL-008` —
  complete restatement; new `FRG-API-026`): every pull entry with no
  library link whose series is not already in the library offers the
  one-click add affordance, not just #1/#0 debuts. When the entry
  carries a source-supplied ComicVine series id (41/72 entries in the
  verified live week), the affordance routes into the Add flow with
  that exact volume resolved and preselected via a new
  lookup-by-volume-id endpoint (owner ask 2026-07-29: don't bounce the
  user into a search that needs editing when the id is already known);
  entries without an id — or whose id ComicVine doesn't recognize —
  fall back to today's name-prefilled search. The separate "New this
  week" strip is retired in favor of inline "New" badges on debut
  entries in the day-grouped agenda (plus a filter affordance).
  No-auto-add posture unchanged: no series record exists until the
  user completes the standard add flow, and the source id stays a
  candidate the user visually confirms — never match authority.
- **Pull enrichment ingestion** (new `FRG-PULL-011`; migration 0029):
  the pull ingest parses and stores the payload fields it currently
  drops — primary cover URL, description, creators, characters, UPC —
  as display-only enrichment columns on the stored entry (D4 untouched:
  still no status on pull entries). Cover URLs are validated at ingest
  against the same host+path constraint the cover proxy enforces and
  stored canonicalized (query stripped); anything else — including the
  source's relative no-cover placeholder — stores as absent, fail
  closed. Text fields ride the existing untrusted-payload sanitization
  (bidi/zero-width strip) and are length-bounded.
- **Path-constrained cover allowlist** (MODIFIED `FRG-META-021` —
  complete restatement): allowlist entries become host rules with an
  optional required path prefix and a per-entry subdomain policy. The
  ComicVine entries keep today's dot-boundary subdomain matching; the
  new LOCG entry is `s3.amazonaws.com` **exact host only** with
  required prefix `/comicgeeks/` — because the host is Amazon's shared
  S3 endpoint, a bare-host or subdomain-matched entry would turn the
  proxy into an open relay for any public S3 bucket (verified live:
  `comicgeeks.s3.amazonaws.com` virtual-hosted style resolves — it and
  every other bucket subdomain must be refused). Dot-segment and
  encoded-traversal URLs are refused before the prefix check; the
  prefix matches on a directory boundary.
- **Calendar covers + enrichment display** (new `FRG-UI-042`): entry
  cards render the stored cover thumbnail through the existing
  authenticated proxy (lazy-loaded, graceful when absent), and an
  entry detail surface exposes description, creators, characters, and
  UPC. The Calendar becomes the first cover-proxy consumer outside
  the add/import pickers.

## Capabilities

### New Capabilities

None — extensions of existing areas.

### Modified Capabilities

- `pull`: MODIFIED FRG-PULL-008 (add-from-any-unmatched-entry,
  CV-id-first routing, inline badges; complete restatement); ADDED
  FRG-PULL-011 (payload enrichment ingestion + fail-closed cover-URL
  validation).
- `api`: ADDED FRG-API-026 (lookup by ComicVine volume id — the
  FRG-API-017 pattern: a variant endpoint gets its own requirement).
- `meta`: MODIFIED FRG-META-021 (host+path-prefix allowlist rules,
  per-entry subdomain policy, LOCG S3 entry; complete restatement).
- `ui`: ADDED FRG-UI-042 (Calendar cover thumbnails + enrichment
  detail; references FRG-UI-018's screen).

## Impact

- Backend: pull/source.py (`_parse_entry` reads the enrichment keys,
  cover-URL validation + canonicalization), pull/models.py
  (`ParsedPullEntry` + `PullEntryRow` columns), pull/repo.py
  (`replace_week` row construction), migration 0029 (additive nullable
  columns on `pull_entries`), api/pull.py (resource carries enrichment),
  api/series.py (lookup-by-volume-id route reusing the existing
  ComicVine client `get_volume` + the lookup route's auth/error
  mapping, interactive lane per FRG-META-022),
  api/cover_proxy.py (allowlist rule shape: host + optional prefix +
  subdomain policy, applied in both the request check and the per-hop
  redirect check).
- Frontend: types.ts (PullEntryRecord enrichment fields,
  AddSeriesNavigationState volume-id prefill), AddSeries.tsx (resolve
  id prefill to a preselected candidate, search fallback),
  CalendarScreen.tsx (inline badges, universal add affordance with
  in-library suppression via the existing title-index seam, cover
  thumbnails, detail surface), reusing `candidateCoverUrl`.
- No dependency changes (stdlib only; SOUP register untouched,
  `tools/soup_check.py` stays green).
- **Security (FRG-PROC-006) — this change grows attack surface**: the
  cover proxy's egress allowlist gains a second, shared-infrastructure
  host serving a second untrusted party's bytes, and a hostile pull
  source graduates from display-text spoofing to supplying *fetch
  targets*. Same change updates `docs/security/threat-model.md` (dated
  delta entry) and `docs/security/risk-register.md` (RISK-025 SSRF and
  RISK-039 pull-source rows extended), with tagged abuse-scenario
  tests: bucket-subdomain refusal, non-prefix S3 path refusal,
  dot-segment/encoded traversal refusal, prefix-lookalike refusal
  (`/comicgeeks-evil/`), hostile payload cover URL failing closed at
  ingest, redirect-hop escape refusal. Gate tier: **full 8-angle fleet
  + Codex** (security-touching, per the M11 pre-design).
- Manual impact (FRG-PROC-011): `docs/manual/user/web-ui.md` Calendar
  section (add-from-anywhere, badges replacing the strip, covers,
  detail surface).

## Non-goals

- No CV involvement for pull imagery/enrichment (budget-free by
  design; the CV lanes of FRG-META-022 are untouched).
- No add affordance on entries whose series is already in the library
  (guard-failed unmatched rows self-heal via refresh; offering "Add"
  there would invite duplicates).
- No pull-side status or matching behavior change (FRG-PULL-003/004
  untouched beyond the additive columns).
- No configurable allowlist (per-host-by-change posture stands; the
  rule shape generalizes, the entries stay code).
- Single-pull-source fallback idea (pre-design stretch) — not taken;
  banked for later.

## Approval

Proposed under the M11 standing grant (owner approval 2026-07-27,
recorded in the m11-import-intelligence pre-design's Approval section,
commit 562b16f). No intent-presuming default changes: the add
affordance remains strictly user-driven (no-auto-add posture restated
in the delta), and enrichment is display-only. The allowlist growth is
the pre-design's named scope for this change and lands with the full
security tier it prescribed.
