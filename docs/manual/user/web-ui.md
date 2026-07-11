# The web UI

foragerr's web interface follows the Sonarr/Radarr design school: a dark left
sidebar for navigation, toolbar-driven pages, poster and table views, and overlay
modals for focused tasks. If you have used Sonarr or Radarr, you already know your
way around — the ant/foraging identity appears only as accent color, logo, and
naming, never as a different layout language.

Open it at `http://<your-tailnet-address>:8789/`. Everything the UI shows comes
from the same REST API documented throughout this manual, and updates arrive live:
a WebSocket connection pushes resource-change notifications (series, queue,
commands), so grabs, imports, and refreshes appear without reloading the page. If
the connection drops, the UI reconnects automatically with backoff.

## The shell

Every screen renders inside a fixed three-part frame — the sidebar never moves,
and only the content region scrolls:

- **Sidebar** (left): the logo lockup, then the navigation list, then a status
  footer. Nav entries carry live count badges where they help — **Comics** shows
  your library's series count, **Queue** shows the number of tracked downloads,
  and **Wanted** shows how many series have missing issues (in an amber warn
  style). The active screen's entry is highlighted with a green accent bar. The
  nav lists only screens that exist today; entries for planned screens appear in
  the release that ships them. The footer shows a health pulse and the running
  version (e.g. "Foragerr 0.4.0 — all healthy"); it turns amber when the Health
  screen has active warnings. A small connection dot sits at the right of the
  footer: green when the live WebSocket is connected, red when it drops. While
  the socket is down the footer text reads "reconnecting…" (rather than claiming
  "all healthy") until the connection is re-established, so the words never
  contradict the red dot. The footer is a screen-reader live region, so assistive
  tech announces these state changes. Fonts (Roboto) and icons (Font Awesome) are
  served from foragerr itself — nothing is fetched from an external CDN, so the UI
  works fully offline on your tailnet.
- **Global header** (top): the library quick-search on the left (see below) and
  quick-access buttons to the Health and System screens on the right.
- **Page toolbar** (below the header): each screen's own primary actions and view
  controls.

A "Skip to content" link is the first thing keyboard focus reaches (press Tab
when the page loads): it is hidden until focused, and activating it jumps past the
sidebar and header straight to the scrolling content region.

## Library

The Library index lists every series in one of three view modes — Posters,
Overview, or Table — switched from the toolbar, with sorting, filtering, and a
text filter alongside them; see `user/library.md` §The library index for the
full set of controls. Posters come from the local cover cache — nothing is
fetched from ComicVine at view time. Clicking a series opens its detail page: a
blurred-cover hero with the series' key facts and an action row (search,
refresh, edit, delete, and a **More** menu for rescan/rename), and a bordered
panel below it with an Issues/Collections toggle — a dense issue table with
bulk selection, and a tab for declared trade containment. See
`user/library.md` §The series detail screen for the full anatomy.

## Adding a series

Add Series searches ComicVine and returns candidates **ranked by relevance** —
closest title match first, publication-year proximity as the tiebreak when your
term carries a year — so the volume you meant is normally at the top rather
than buried in alphabetical order. Nothing is filtered out by the ranking: every
candidate the search found is still in the list, just ordered.

Each result is an expandable card showing the cover, title and year, publisher,
issue count, and a short description; a series already in your library carries
an **In library** badge and can't be added twice. Expanding a card opens the
add panel inline: root folder and format profile selects, the monitoring
strategy as a segmented control, a **Collect as** choice (Single Issues /
Collected Editions — leave it untouched and foragerr types the series from its
title cues as usual; an explicit choice locks the book-type so refreshes never
overwrite it, and it can be refined on the series afterwards), and the
optional start-search-for-missing-issues toggle, before the add flow kicks off
its chained refresh → scan → optional search.

As you type (three characters or more) a debounced autosuggest dropdown offers up
to about ten candidates straight from ComicVine, without waiting for the full
search below — pick one and it opens the exact same add panel a full-search
result would. It's an accelerator, not a replacement: the full search stays the
authoritative one, so submitting it (⏎ or the Search button) always runs for
real, and re-submitting an identical term after an error or a degraded/capped
result retries instead of doing nothing.

A search that can't be completed is never presented as "no results": if ComicVine
rejects the API key (unset or invalid) the screen says so and links straight into
Settings → General, where the key is actually set — the autosuggest dropdown
shows the same guidance if it hits a rejected key; if the search degraded mid-way
(rate limiting, a ComicVine outage)
any candidates found so far render with a "results may be incomplete" notice —
or, when nothing at all was retrieved, an explicit failure message; and a search
that hit the result cap says so and advises a narrower term. Re-searching the
same term always retries for real. Only a fully completed search with zero
matches shows the plain no-results state.

## Quick search

The search box in the header, present on every screen, jumps you straight to a
series you already own. Start typing and it matches against your library's
titles and aliases entirely locally — there is no ComicVine request and no
network round trip at all, so it works even if ComicVine is unreachable or the
key isn't configured. Matches are ranked exact and prefix hits first, then
word-boundary and substring hits.

Navigate the list with the arrow keys, press Enter to jump to the highlighted
series' detail page, or Escape to dismiss it. The last row is always
**"Search ComicVine for '\<term\>'…"**, whether or not any local matches were
found — selecting it takes you to Add Series with your term already filled in
(and its autosuggest already running), bridging "it isn't in my library yet"
straight into adding it.

## Library Import

Library Import (sidebar) mass-ingests an existing collection: pick a root
folder, run a scan, and review the staged series groups — each with file count,
parse confidence, and a proposed ComicVine match (poster, name, year,
publisher) or an explicit no-match state. Confirm or skip groups, correct a
match with the inline ComicVine search, then execute with batch add options
(format profile, monitoring, search-on-add). Each group reports its outcome —
imported, or blocked with the pipeline's verbatim reasons. Groups without a
plausible match are never importable on a guess, an unconfigured-roots state
points you at Settings, and a scan that finds nothing to import says so. The
inline ComicVine search used to correct a match shows the same rejected-key
guidance (linking to Settings → General) as Add Series. See `import.md` for how
the scan, in-place registration, and re-scan semantics work.

## Calendar

The Calendar is the weekly pull view: a date-grouped agenda of what ships in a
given store week, not a month grid — comics land in one Wednesday drop, and the
layout embraces that with a "New Comic Day" badge on Wednesday and a "Today"
marker. Navigate weeks with ‹ / › and jump back with **This Week**; the week you
are viewing is in the URL, so back/forward and reloads keep your place. The view
defaults to **Following** — releases from series in your library, with a
"+N more titles shipping" note for everything else — and flips to
**All releases** to show the full week, publisher-filterable either way. Each
release card carries its live state (wanted, downloading, downloaded,
unmonitored), computed from the issue and queue exactly like everywhere else;
nothing is stored on the calendar itself. Cards for issues in your library offer
want/skip and an immediate search — the same operations the Wanted screen uses.
Debut issues (#1s) from series you don't have appear in a separate
**New this week** strip with a one-click route into the standard add flow;
foragerr never adds a series by itself. Next week's solicited releases appear
under forward navigation once the pull source has published them, marked as not
yet released, and the whole view keeps working from your local metadata when the
external pull source is unconfigured or down.

## Queue

The Queue screen shows every tracked download live: state (queued, downloading,
import pending, importing, imported, failed), a human-readable status message, and
— for blocked imports — the exact reasons the pipeline recorded (`import.md`).
Items can be removed from here; an item that is actively importing refuses removal
until the import finishes, so files are never yanked out from under the importer.
Import-blocked rows carry a **Manual import** action that opens the resolution
overlay (`import.md`), and the toolbar's path picker runs the same overlay over
any folder.

## History

Activity → History is the paged feed of everything the pipeline did: grabs,
imports, upgrades, blocked/failed imports, failed downloads, deletions, and
renames — each linked to its series/issue, filterable by event type, with
expandable details carrying the verbatim reasons for blocked and failed events.
A grab and its import share a download id, so one acquisition reads as one
story. Identical blocked retries are recorded once — a permanently stuck item
shows its blocked state live in the queue rather than re-writing the same
history row every minute.

## Wanted

Wanted lists every missing issue — monitored, published, and file-less —
computed live from the library (there is no stored "wanted" flag to drift).
Each row offers automatic search and the interactive search overlay, and
**Search all** runs one backlog search over the listed set with its command
status visible. Importing a file removes a row instantly; deleting a file
returns it.

## Blocklist

Activity → Blocklist shows every release banned by a failed download — source
title, series/issue, indexer, date, and the verbatim reason. Removing an entry
(singly or in bulk) makes that release grabbable again.

## Interactive search

The interactive search overlay shows **every** candidate release the decision
engine evaluated — including the rejected ones, each with its verbatim rejection
reasons (wrong format, below cutoff, blocklisted, size bounds…). Nothing is
filtered out silently: what the automatic search saw is exactly what you see, and
any listed release can be grabbed manually.

## Settings

Settings covers General, indexers, download clients, and Media Management.
Indexers and download clients use the same schema-driven
form: the server describes each provider implementation's fields and the UI
renders them, so a new provider type needs no UI change; General and Media
Management are each their own dedicated single-form screen. Secret fields (API
keys) are write-only — the form shows that a value is stored but never displays
it back. Every provider has a Test button that performs a live connectivity
check before you save.

On a fresh install, Indexers and Download Clients are not empty: foragerr seeds
one **GetComics** DDL indexer and one **built-in DDL** download client — but
both ship **disabled**, so nothing is searched or downloaded until you opt in
by enabling the pair (Settings → Indexers → GetComics, and Settings →
Download Clients → GetComics). No credentials are needed once enabled. Both
are ordinary provider rows — delete either (or both) if you don't want them,
and they are never re-created; only a genuinely first-run database gets
seeded. See `downloads.md` for what the DDL pipeline does and the security
rationale for the opt-in default.

### General

The General screen holds the one truly global credential: the ComicVine API
key. Its field is masked and write-only like every other secret field — it
shows a "key is set" hint, never the value, and saving a blank field leaves the
stored key untouched. A **Test** button checks the currently-saved (or
environment-supplied) key against ComicVine and reports success or failure; it
is disabled while you have an unsaved edit in the field, since testing then
would silently check the *old* key and misreport it as belonging to what you
just typed.

If `FORAGERR_COMICVINE_API_KEY` is set in the environment, the field renders
read-only with a note that it is environment-managed — the environment variable
always outranks a UI-saved value, so editing here would have no effect until the
variable is unset. Otherwise, saving here writes the key into `config.yaml` (the
same file `configuration.md` documents) and applies it immediately, without a
restart.

A rejected-ComicVine-key error anywhere in the app (Add Series, autosuggest, the
Library Import inline search) links straight here.

### Media Management

The Media Management page controls naming and file handling: the rename toggle,
file and folder naming templates (with a `?` token cheatsheet and a live example
that recomputes as you type), illegal-character policy, transfer mode, the
existing-library import mode, the recycle bin (path + retention), and duplicate
handling (the same-rank constraint and optional duplicate-dump folder —
`import.md` §Duplicate handling). Template
edits show their effect immediately; nothing changes on disk until you save.

From here (or from a series' **Rename Files** toolbar button) you can open the
**rename preview**: a list of exactly which files would move from their current
names to template-rendered names. Nothing is renamed until you confirm, and the
executed renames match the preview exactly — each one recorded as a history
event.

## System

The System nav group is the operator's view of the running application:
Status, Health, Tasks, and Logs.

### Status

Version and build (version string, commit, build date), the managed paths
foragerr is using (config directory, database path, backups directory,
number of registered root folders), and runtime info (uptime, Python version,
OS). Nothing sensitive is shown here — no provider key or other secret ever
appears on this screen.

### Health

The Health screen answers "is anything wrong that I should act on?" — it is
deliberately distinct from the container-level `/health` liveness probe Docker
uses. It has two parts:

- **Warnings** — the current, actionable problems: a backed-off indexer or
  download client, a low-disk-space condition (free space below 1 GiB on the
  config volume), a failing database integrity check, an overdue scheduled
  backup, and so on. Each item names its source
  and carries a remediation hint (e.g. "verify its URL and API key", "stop the
  container and restore the most recent good backup"). A fully healthy system
  shows an explicit **"All healthy — no active warnings"** state rather than
  an empty-looking screen.
- **Components** — every tracked component (ComicVine, each indexer, each
  download client/DDL provider, the scheduler, the database, each root
  folder, disk space) with its current state (OK / Degraded / Error), its
  last-success and last-failure times, and — for a provider in back-off — how
  long it stays disabled.

The screen polls automatically, so a component that recovers (an indexer's
back-off clears, disk space is freed) drops off the warnings list on its own,
with no need to reload the page or restart the container.

### Tasks

The Tasks screen lists every scheduled task — including the daily
`backup-database` task — with its interval and its last/next run time. The
`creators-backfill` row is a one-time job (it gathers creator credits for
series added before the feature existed): it runs by itself once and then
sits with a far-future next run; its **Run Now** button re-runs it safely
if you ever want to. Every
row has a **Run Now** button to force-run it immediately (resetting its
timer); the `backup-database` row's button is labelled **"Back up now"**
instead, but it is the exact same force-run action. A running task shows its
live status inline, and the last/next-run columns update once it finishes.
See `../admin/configuration.md` → "Scheduled backups" for what the backup
task actually does, and `../admin/deployment.md` → "Restoring from a backup"
for how to use what it writes.

### Logs

The Logs screen is the in-app answer to "what is the backend actually doing" —
useful when, say, a series isn't downloading and the reason isn't obvious from
the Queue or Health screens. It renders a dense table (time, a color-coded
level pill — ERROR red, WARNING amber, INFO neutral, DEBUG muted — logger
name, and message), newest first, with a minimum-level filter and a
logger-name-prefix filter above the table.

**Follow** (on by default) keeps the table pinned to the newest records,
polling the server every couple of seconds; turn it off to page back through
older records with the standard page controls, which also pauses polling. An
empty table says so explicitly ("No log records buffered yet…") rather than
rendering blank, and a failed request says loading failed rather than showing
nothing.

The table only ever shows what's currently in the backend's in-memory log
buffer — it is **not a persisted log**. Restarting the container clears it, and
it only holds a bounded number of the most recent records (configurable; see
`../admin/configuration.md` → "Logs and diagnostics"). For anything you need
to keep past a restart, use the container's stdout/log file instead.
