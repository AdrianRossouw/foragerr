# m11-discovery-surface — design

## Context

The pull backbone (FRG-PULL-002/003/004) fetches the talkhard weekly
payload, parses six fields per entry (`_parse_entry`,
`pull/source.py`), stores them keyed `(week, entry_identity)` with
replace-on-refresh, and matches them to the library. The Calendar
screen (FRG-UI-018) projects that store; its only add affordance lives
in the FRG-PULL-008 "New this week" strip, gated to `new_series`
entries. The cover proxy (FRG-META-021, `api/cover_proxy.py`) serves
CV candidate covers same-origin behind auth, with a module-constant
host allowlist checked by `_host_allowed` (exact or dot-boundary
subdomain) at request time and at every redirect hop.

Live payload facts (verified 2026-07-29, weeks 29/30 fetched raw):

- `covers`: list of `{url, is_primary}`; every real URL is
  `https://s3.amazonaws.com/comicgeeks/comics/covers/large-<id>.jpg?<ts>`
  (path-style, shared S3 endpoint, volatile query cache-buster);
  no-cover entries carry the relative placeholder
  `/assets/images/no-cover-lg.jpg`.
- `description` (~92% of entries), `creators` (`{creator_id, role,
  name}`), `characters` (`{character_id, name}`), `upc` (~83%).
- The same object is reachable virtual-hosted-style at
  `comicgeeks.s3.amazonaws.com`, and query-less URLs serve 200.

## Goals / Non-Goals

**Goals**: act-on-anything Calendar (add affordance on every unlinked,
not-in-library entry); covers and enrichment stored at ingest and
rendered; allowlist growth that does NOT create an open S3 relay.

**Non-goals**: see proposal (no CV spend, no status on pull entries,
no configurable allowlist, no add on in-library guard-failed rows).

## Decisions

**D1 — Allowlist entries become rules: `(host, subdomain_policy,
required_prefix)`.** The flat frozenset cannot express the S3
constraint. `COVER_HOSTS` becomes a tuple of small rule objects:
ComicVine entries keep dot-boundary subdomain matching with no prefix
(today's behavior, restated); the LOCG entry is exact-host
`s3.amazonaws.com` + required prefix `/comicgeeks/`. Rationale: the
shared S3 endpoint means host alone authorizes every public bucket on
the internet — including virtual-hosted bucket subdomains, which is
why this entry's subdomain policy must be exact-only. Alternative
considered: allowlist the virtual-hosted `comicgeeks.s3.amazonaws.com`
host instead (no path logic needed) — rejected because the payload
URLs are path-style; rewriting them into virtual-hosted form at ingest
adds a transformation layer whose failure modes (bucket names with
dots, region endpoints) are worse than one prefix check at the choke
point.

**D2 — Prefix checked on the canonicalized, decoded path at both
gates.** The request-time check and `_hop_check` share one rule
evaluator. Before the prefix test the path is percent-decoded once and
refused outright if it contains any dot-segment (`.` / `..` as a
segment, encoded or not) or backslash; the prefix must end at a
directory boundary (`/comicgeeks/` exactly, so `/comicgeeks-evil/`
fails). Single-decode-then-refuse avoids double-decode ambiguity
(`%252e`). Redirect hops re-run the full rule evaluation, so an
allowlisted target redirecting to `s3.amazonaws.com/other-bucket/` is
refused mid-flight.

**D3 — Ingest stores one canonical cover URL, validated fail-closed.**
`_parse_entry` picks the primary cover (`is_primary`, else first),
strips the query (stable idempotent storage per FRG-PULL-003 —
the `?ts` cache-buster changes between fetches — and stable proxy
cache keys; verified query-less URLs serve), and stores it only if it
passes the SAME rule evaluator the proxy enforces (importing the
proxy's evaluator, one source of truth). Everything else — relative
placeholder, http, off-host, off-prefix, traversal — stores NULL.
Rationale: the stored URL is a future fetch target; validating at the
trust boundary (ingest) means a hostile source cannot even persist a
poisoned URL, and the proxy check remains as defense in depth.
Alternative: validate only at the proxy — rejected; it leaves hostile
URLs dormant in the DB and every future consumer must remember to
re-validate.

**D4 — Enrichment is five nullable columns, JSON for the lists.**
`cover_url TEXT`, `description TEXT`, `upc TEXT`, `creators TEXT`
(JSON array of `{role, name}`), `characters TEXT` (JSON array of
`{name}`) on `pull_entries`, migration 0029, additive and inert to
older code. IDs from the source (creator_id/character_id) are dropped
— they're LOCG-internal, we link nothing to them. Text fields pass the
existing bidi/zero-width sanitization and per-field length caps
(description 4000 chars, upc 64, names 256, lists capped at 64
entries) inside the existing payload byte-cap. Display-only: D4's
no-status invariant and the schema-inventory guard test extend to
assert no status column arrived.

**D5 — Universal add affordance stays client-gated by the existing
title index.** The strip's in-library suppression
(`libraryTitles`, casefolded exact title match) moves to card level:
any entry with `matchedIssueId == null` whose series title is absent
from the library index renders the Add button (prefilled `/add` nav,
same seam). `new_series` entries render an inline "New" badge; the
separate strip section is removed. Rationale: reuses the proven seam,
no API change for the affordance; the suppression heuristic's known
imprecision (title collision across volumes) errs toward suppressing
an Add, never toward auto-adding. The `state` machine
(`pending_refresh` etc.) is untouched.

**D6 — CV-id-first add routing (owner ask, 2026-07-29).** When a pull
entry carries `cv_series_id` (41/72 in the verified live week), the
add affordance navigates with `{ prefillCvVolumeId, prefillTerm }`;
the Add screen resolves the id through the new
`GET /series/lookup/volume/{id}` (FRG-API-026 — reusing
`ComicVineClient.get_volume` + the term lookup's error mapping,
interactive lane) and renders that single candidate preselected with
its add-options panel; a 404-class resolution or any upstream failure
degrades to the `prefillTerm` search with a notice. Rationale: the
payload's id is exactly the datum the search asks the user to
rediscover by hand; resolving it keeps the user's confirmation step
(no-auto-add, id-as-candidate posture) while removing the term
editing. Alternative — trusting the id straight into `POST /series` —
rejected: that would make a source-supplied id add authority,
crossing the FRG-PULL-004 line. `issueid` is nearly always null in
the live payload, so series grain is the only routing grain.

**D7 — Covers lazy-load through the existing proxy endpoint.**
Cards use `candidateCoverUrl(entry.coverUrl)` with native
`loading="lazy"` and an `onError`/absent fallback to today's tinted
spine. The proxy's LRU (64) and semaphore (4) stay as-is for this
change: a week renders ~70 covers, lazy-loading keeps concurrent
fetches to the viewport, and `Cache-Control: private, max-age=86400`
makes the browser the real cache. If rig use shows thrash, bumping the
LRU is a follow-up, not a spec matter.

## Risks / Trade-offs

- [Shared-host allowlist entry is one policy bug from an open S3
  relay] → exact-host + directory-boundary prefix + traversal refusal,
  enforced by one shared evaluator at request AND hop time, pinned by
  tagged abuse tests (bucket subdomain, prefix lookalike, encoded
  traversal, hop escape); full-fleet gate attacks it.
- [Hostile pull source supplies fetch targets, not just display text]
  → fail-closed ingest validation via the same evaluator; RISK-039
  updated to record the graduated trust; sanitization + caps on all
  new text fields.
- [S3/LOCG changes URL shape and covers silently vanish] → fail-closed
  NULL is the designed degradation (Calendar renders spines as today);
  health is NOT wired to cover presence by design — cosmetic, not
  operational.
- [Title-index suppression misses a retitled in-library series → Add
  offered on something tracked] → Add flow is user-driven and the Add
  screen shows the library state; worst case is a redundant nav, never
  a duplicate series (add flow itself guards).
- [Enrichment bloats `pull_entries` rows] → per-field caps; weeks are
  replace-on-refresh so the table stays bounded by retained weeks.

## Migration Plan

Migration 0029: five additive nullable columns on `pull_entries`; no
data rewrite; forward-only per house pattern; inert to older code.
Existing stored weeks show no covers until their next refresh
repopulates them (scheduled refresh handles it; no backfill command).
Rollback = revert the release tag; columns are inert.

## Deferred follow-ups (recorded at the security gate)

Real but judged not worth churning the gated branch; a later cleanup
should pick them up:

1. **Ingest list-cap iteration bound**: the creators/characters caps
   count *accepted* items, so a hostile list of all-invalid entries is
   iterated in full (bounded only by the 4 MB body cap). Break on items
   examined, not accepted.
2. **List-projection payload trimming**: the week endpoint ships every
   enrichment field on every row regardless of whether the card is
   expanded; a hostile maximal week inflates the transfer. Consider
   dropping `description`/`characters` from the list projection and
   serving them from a per-entry detail fetch.
3. **AddSeries autosuggest lapse**: after a CV-id resolve, editing the
   search box suppresses autosuggest until Search is pressed; the
   suppression should lapse once the input diverges from the prefill
   term.
4. **`normalizeTitle` vs `fuzzyMatch`**: the Calendar's in-library
   suppression uses trim+lower, weaker than `lib/fuzzyMatch`'s
   whitespace-collapsing normalization, so a doubled-space library
   title errs toward *offering* Add (harmless — the add flow's own
   `have_it` guard blocks a duplicate — but inconsistent with the
   design's "errs toward suppressing" note). Align them.
5. **Status badge vs interactive chip**: the "New" badge shares the
   accent-tint treatment of the Add/filter chips beside it; give the
   non-interactive badge a distinct token so it doesn't read as a
   false affordance.

## Open Questions

None blocking. The detail surface's exact form (popover vs expando) is
an implementation call within FRG-UI-042's scenarios.
