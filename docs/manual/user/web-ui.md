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

A search that can't be completed is never presented as "no results": if ComicVine
rejects the API key (unset or invalid) the screen says so and points you at
Settings; if the search degraded mid-way (rate limiting, a ComicVine outage)
any candidates found so far render with a "results may be incomplete" notice —
or, when nothing at all was retrieved, an explicit failure message; and a search
that hit the result cap says so and advises a narrower term. Re-searching the
same term always retries for real. Only a fully completed search with zero
matches shows the plain no-results state.

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
