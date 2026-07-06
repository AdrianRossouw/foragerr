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

## Library

The Library index lists every series as a poster grid or a table (toggle in the
toolbar), with sorting and filtering. Posters come from the local cover cache —
nothing is fetched from ComicVine at view time. Clicking a series opens its detail
page: a hero band with the series' key facts, per-issue rows with monitored
toggles, each issue's file status, and buttons that dispatch real commands —
refresh metadata, rescan the series folder, or search for an issue.

## Adding a series

Add Series searches ComicVine and annotates each candidate with plausibility
signals (issue counts, years) so the right volume is easy to pick. The add panel
lets you choose the root folder, format profile, and monitoring options before the
add flow kicks off its chained refresh → scan → optional search.

As you type (three characters or more) a debounced autosuggest dropdown offers up
to about ten candidates straight from ComicVine, without waiting for the full
search below — pick one and it opens the exact same add panel a full-search
result would. It's an accelerator, not a replacement: the full search stays the
authoritative one, so submitting it (⏎ or the Search button) always runs for
real, and re-submitting an identical term after an error or a degraded/capped
result retries instead of doing nothing.

A search that can't be completed is never presented as "no results": if ComicVine
rejects the API key (unset or invalid) the screen says so and points you at
Settings — the autosuggest dropdown shows the same guidance if it hits a
rejected key; if the search degraded mid-way (rate limiting, a ComicVine outage)
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
points you at Settings, and a scan that finds nothing to import says so. See
`import.md` for how the scan, in-place registration, and re-scan semantics
work.

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

Settings covers indexers, download clients, and Media Management. Indexers and
download clients use the same schema-driven
form: the server describes each provider implementation's fields and the UI
renders them, so a new provider type needs no UI change; Media Management is its
own dedicated screen (naming, transfer mode, recycle bin). Secret fields (API keys)
are write-only — the form shows that a value is stored but never displays it back.
Every provider has a Test button that performs a live connectivity check before
you save.

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
