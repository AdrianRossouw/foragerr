# Downloads

foragerr acquires releases through **download clients**: SABnzbd (usenet) and a
built-in direct-download (DDL) client for GetComics. Both implement the same
interface, so the rest of foragerr — the queue view, tracking, import handoff,
failure handling — treats them identically. There is no separate "DDL world"; a DDL
grab looks like any other download except for its protocol/client fields.

**A fresh install ships with the GetComics/DDL pair seeded but disabled — enable
it in Settings to start acquiring.** On first startup against a genuinely empty
database, foragerr seeds the GetComics indexer and the built-in DDL client once,
so the keyless pipeline is pre-configured and discoverable — but **both rows are
created disabled** (the indexer's automatic-search and RSS toggles are off too),
so nothing is searched, scraped, grabbed, or downloaded until you deliberately
turn them on. Wanted issues simply stay wanted until then. No credentials are
needed for either, so activation is one toggle, not a configuration task:

1. **Settings → Indexers** — open the seeded **GetComics** indexer and enable it
   (turn on Enable, plus Automatic Search / RSS if you want unattended grabbing).
2. **Settings → Download Clients** — open the seeded **GetComics** built-in DDL
   client and enable it.

Once both are enabled, the pipeline searches and downloads exactly as before,
with no further setup. This is a deliberate **opt-in** posture: enabling the
GetComics indexer starts outbound scraping of a third-party site
(getcomics.org), so foragerr never begins that on its own — you decide when. If
you don't want DDL at all, just leave the pair disabled or delete it (Settings →
Indexers / Download Clients); a deleted seeded row is permanent and never
re-created. See `docs/security/threat-model.md` (the `m2-first-run-defaults`
delta, amended by `ddl-optin-seeding`) and RISK-015/RISK-016 in
`docs/security/risk-register.md` for the accepted risk this opt-in posture
carries once you enable it (single hardcoded upstream; scraping-automation ToS
considerations). SABnzbd and any Newznab indexer (DogNZB, NZB.su) remain opt-in
too — they need credentials, so they are never seeded automatically.

## Configuring a download client

Each client is a provider row: implementation, JSON settings, enabled flag, priority,
and a "remove completed downloads" flag. `GET /api/v1/downloadclient/schema` and
`POST /api/v1/downloadclient/test` mirror the indexer provider shape (settings form
metadata, live connectivity test). When a release is grabbed, foragerr routes it to
whichever enabled client matches the release's protocol.

If the matched client is unreachable at grab time, the grab is retried later rather
than lost — the release stays valid in the search cache and grabbing can be retried.

### SABnzbd

foragerr fetches the NZB bytes itself from the indexer (never asks SABnzbd to fetch
them), validates the bytes (non-empty, parses cleanly, contains at least one file
segment), and uploads them to SABnzbd via `mode=addfile` with a configurable category
(default `comics`) and priority. This keeps indexer credentials off SABnzbd entirely
and rejects mislabelled/hostile payloads before they ever reach SABnzbd.

foragerr polls SABnzbd's queue and history, filtered to the configured category, and
maps SABnzbd's states onto a common status: paused → Paused; queued/grabbing/
propagating → Queued; verifying/extracting/repairing → Downloading; completed →
Completed; failed → Failed (with a disk-full unpack condition mapped to Warning
instead). Encrypted/password-protected history items are flagged and treated as
failed.

If SABnzbd runs on a different host or container than foragerr, configure a remote
path mapping so a completed item's reported output path is rewritten to the path
foragerr can actually read; an unmapped foreign path surfaces as a "check remote path
mapping" warning instead of failing import silently.

### Built-in DDL (GetComics)

The DDL client searches GetComics through an escalating query ladder, followed by
paginated "older posts" browsing up to a configured depth, de-duplicating by post URL
and skipping weekly-roundup posts. Matching posts are fed into the same decision
engine and comparator that ranks usenet releases — DDL results compete on equal
footing, not by a private GetComics-only notion of quality.

For a chosen post, foragerr enumerates every offered download link by quality tier
(HD-Upscaled, HD-Digital, SD, normal) and host (main server, Mega, MediaFire,
Pixeldrain), and picks one according to your configured host-priority order and
quality preference (default: prefer upscaled). Known paywall/shortener links are
rejected outright and never fetched.

DDL downloads run from a persistent, single-flight queue (default concurrency 1):
items survive a foragerr restart and resume rather than losing their place. Manual
retry, resume, abort, and remove actions are available from the queue.

On a download or verification failure, DDL automatically fails over to the next
untried host in your priority order for the same release; only once every host is
exhausted does the item fail for good and hand off to the standard failed-download
handling described below.

Every completed DDL file is verified before import: its magic bytes must match the
claimed file type, a `.cbz` must open as a real zip containing at least one image, and
it must clear a minimum size floor — a mismatch (e.g. an HTML error page saved with a
`.cbz` extension) counts as a failure and triggers host failover. Downloaded filenames
are always generated by foragerr from library metadata plus the queue id — never taken
from a redirect's final URL or any other value an attacker-controlled server could
influence.

## The queue

The queue view is built exclusively from foragerr's own tracked-download state — it
never polls a download client live at request time. A background tracking pass (about
once a minute, plus immediately after a grab or import) lists items from every enabled
client, matches them to the download that produced them, and advances each one
through a state machine: Downloading → ImportPending → Importing → Imported (or
FailedPending → Failed on failure). Every state is visible in the queue with a
human-readable status message, including items that are blocked pending manual
resolution.

## Failure handling and the blocklist

When a download fails — including encrypted/password-protected results and DDL host
exhaustion — foragerr records it in a blocklist (indexer/source, title, size, publish
date, protocol) and, if auto-redownload is enabled (on by default), immediately
queues a new search for the affected issues. Future candidates are matched against the
blocklist (usenet: same title + indexer + size + publish date; DDL: same source
URL/title) and rejected outright, so the search naturally lands on a different
release instead of re-grabbing the one that just failed. Blocklist entries are visible
and removable — deleting one makes that release grabbable again.

## Import

Once a download completes and is verified, it enters the import pipeline described in
`import.md`: the file is verified as a structurally safe comic archive, matched to its
series and issue, checked against the import decision rules, renamed by your naming
template, and moved into the series folder. Anything that cannot be imported is kept
and shown as import-blocked with its reasons — see that chapter for the full flow.
