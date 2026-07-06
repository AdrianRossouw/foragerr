# Metadata refresh (ComicVine)

All series and issue metadata comes from ComicVine. foragerr talks to ComicVine
through a single client with mandatory timeouts, TLS verification always on, and a
process-wide rate limit (at least 2 seconds between any two ComicVine requests by
default, configurable) — this applies across every concurrent operation, including
cover downloads, so a busy foragerr instance never bursts ComicVine traffic.

## Searching for a series to add

Series search (`GET /api/v1/series/lookup`) queries ComicVine by name and returns
candidates annotated with plausibility signals — publication-year range, issue-count
sanity when you gave a target issue, and whether the series is already in your
library — but foragerr never auto-picks a candidate for you. Results from publishers
on a configurable ignore list (e.g. variant-cover/reprint-only imprints) are excluded
outright; other plausibility signals only annotate, they don't filter. Results are
capped (around 1000 candidates) with a visible truncation warning if a search would
exceed that.

### Troubleshooting: search returns nothing

A genuinely empty result only appears when ComicVine completed the search and
matched nothing. Other outcomes are reported distinctly:

- **"ComicVine API key missing or invalid"** — the lookup was rejected outright
  (HTTP 401/403 upstream). Set `comicvine_api_key` (or the
  `FORAGERR_COMICVINE_API_KEY` environment variable — see the admin manual,
  `secrets.md`) and search again. An invalid key fails every request, so foragerr
  reports it as an error instead of pretending the search found nothing.
- **"Results may be incomplete"** — the search degraded part-way (rate limiting,
  a ComicVine outage, a malformed page). Whatever candidates were retrieved are
  shown; re-run the same search in a moment for the full list. If the degrade
  happened on the very first page, the screen reports it as a lookup failure
  instead of showing an empty list with a footnote.
- **"Too many results"** — the search hit the configured result cap (around
  1000 candidates). Retrying will not change this; use a narrower term (add a
  year, a fuller title) instead.

## What a refresh does

A metadata refresh re-fetches a series' volume and issue list from ComicVine and
reconciles it against what's stored locally, keyed by ComicVine issue ID, in one
transaction:

- New issues are inserted (monitored according to the series' monitor-new-items
  policy — see `library.md`).
- Changed fields on existing issues are updated.
- Issues that disappeared at the source are deleted locally — **unless** the fetch was
  partial/incomplete (a mid-pagination failure), in which case no deletions happen at
  all, to avoid deleting issues foragerr simply failed to fetch. Issues that have a
  file attached are never hard-deleted even when the source is fully synced; the
  record stays visible for manual review.

Refresh runs automatically as part of the add-series chain, and manually on demand.
Scheduled/periodic refresh with staleness skip-rules is a later-milestone feature; M1
covers on-add and manual refresh.

## Data integrity guarantees

- Non-integer issue numbers (`1`, `1.5`, `1.MU`, `½`) are preserved verbatim as text,
  never coerced to a number, alongside a computed sort key so issue lists display in
  correct reading order.
- Missing fields (publisher, start year, store date, etc.) are stored as typed nulls —
  never sentinel strings like `'None'`, `'Unknown'`, or `'0000-00-00'`.
- An issue lacking an issue number is recorded (unmonitored) with a visible warning,
  rather than silently dropped, so your have/total counts stay honest.

## Cover art

Series and issue cover images are downloaded through the same rate-limited, egress-
controlled path and cached locally under the config directory. The UI (once it exists)
and OPDS serve covers only from that local cache — your browser or reader never makes
a direct request to ComicVine. A cover is only re-fetched when ComicVine's image URL
for it actually changes.

## ComicVine content is treated as untrusted

Series/issue names, aliases, and descriptions from ComicVine are wiki-editable by
third parties, so foragerr sanitizes every ComicVine-originated string on ingest (HTML
stripped to text, whitespace collapsed, length capped) before it is stored, rendered,
or used to build a folder name or a downstream search query. You should never see raw
HTML in the UI, and a hostile title containing path separators cannot escape into an
unsafe folder name.
