# Library & series management

foragerr tracks comic series the same way Sonarr tracks TV series: you add a series
from ComicVine, it becomes part of your library, and foragerr keeps its issue list and
on-disk files in sync going forward.

## The library index

The Library screen (**Comics** in the sidebar) lists every series in the library. A
toolbar above the list carries a text filter, a view-mode switcher, and three
menus — **Options**, **Sort**, and **Filter**.

### View modes

The switcher renders the same series list three ways:

- **Posters** — a responsive card grid (size set by the Options menu). Each card
  shows the cover, a monitored bookmark, a publisher chip, an owned/total
  progress strip, and the title with a status/year subline.
- **Overview** — one row per series: cover thumbnail, title with a status pill
  (Continuing/Ended), publisher and status/year line, and a wide progress bar
  with a percent-complete label.
- **Table** — a dense table with monitor icon, Title (with a book-type badge),
  Publisher, Issues (mini progress bar), Status, and Year columns.

Clicking a card, row, or table row opens that series' detail page.

### Options menu

- **Poster size** — S / M / L; affects the Posters view only.
- **Group volumes** — switches to the grouped display described under
  "Grouping series by franchise" below. Unlike the other toolbar choices, this
  toggle does not persist — it resets to off each time the page loads.

### Sort menu

Orders the list by **Title** (default), **Publisher**, **Issues owned** (most
owned first), or **Year** (newest start year first); ties under every non-title
sort fall back to title order. The active choice carries a check mark.

### Filter menu

The main section filters by status — **All**, **Monitored**, **Missing issues**,
or **Continuing** — each showing a live count for the current text filter and
editions choice. A separate **EDITIONS** section filters independently by
collected-edition typing: **All editions**, **Collected only**, or **Single
issues only** (see "Collected editions (trades)" below); its counts likewise
reflect the current text filter and status choice. The two filters combine —
picking Monitored and Collected only shows monitored trades.

### Text filter and the count line

The toolbar's search box narrows the list to series whose title contains the
typed text. The count line above the list reports the library as a whole —
`N comics · N monitored · N with missing issues`, with the monitored and
missing-issues figures in their semantic colors — independent of any active
filter.

### What persists

View mode, poster size, sort choice, and both filter choices (status and
editions) are remembered across browser sessions. The text filter and the
group-volumes toggle are not — both reset when the page reloads.

## Adding a series

`POST /api/v1/series` (via the UI's Add Series screen — see
`user/web-ui.md`) adds a series by its ComicVine volume ID.
Adding a series runs a fixed sequence:

1. **Fetch and persist metadata** — the series and its issue list are pulled from
   ComicVine and stored.
2. **Apply add-options** — the root folder, format profile, monitoring strategy, and
   whether to search immediately are recorded on the series.
3. **Build and validate the series path** — the on-disk folder is created under the
   chosen root folder.
4. **Scan the path** — any files already present under that path are matched to
   issues.
5. **Optional search** — if search-on-add was requested, a search for missing
   monitored issues is queued.

Each step runs as a separate, observable command (visible via the command/job-history
API), and the sequence is restart-safe: if foragerr restarts mid-add, the remaining
steps resume rather than the add restarting from scratch.

Adding a series rejects up front if: the ComicVine volume ID does not exist, the root
folder is not registered, or the volume is already in the library (one series per
ComicVine volume ID, enforced by a uniqueness constraint).

## Monitoring: two independent flags

Every issue is only eligible for automatic acquisition when **both** its own
`monitored` flag and its series' `monitored` flag are set. This two-level design means:

- Unmonitoring a whole series suppresses all of its issues from the wanted list, even
  though the issues themselves stay marked monitored underneath.
- Re-monitoring the series brings its previously-monitored, still-missing issues back
  into the wanted list — without touching any individual issue flag.
- "Wanted" is never a stored status. It is computed on the fly as: series monitored
  AND issue monitored AND issue released AND no file present. There is no "wanted"
  column to get out of sync — importing a file removes an issue from Wanted, deleting
  the file returns it, both with no explicit status write.

### Add-time monitoring strategy

When you add a series, you choose a monitoring strategy that is applied once, right
after the issue list is populated:

| Strategy  | Effect |
|-----------|--------|
| all       | monitor every issue |
| future    | monitor only issues not yet released |
| missing   | monitor only issues you don't already have on disk |
| existing  | monitor only issues you already have on disk |
| first     | monitor only the first issue in reading order |
| none      | monitor nothing |

The strategy is applied exactly once, then the series' add-options are cleared. Issues
discovered later (via metadata refresh) are governed by the separate **monitor-new-items
policy** (below), not by the add-time strategy.

### Monitor-new-items policy

Each series carries a monitor-new-items policy of `all` or `none`. This decides whether
an issue newly discovered on a later metadata refresh starts out monitored. This is
what makes foragerr automatically pick up newly-announced issues of an ongoing series
without you touching anything, if the policy is `all`.

## Root folders and series paths

You configure one or more root folders. When you add a series without an explicit
path, foragerr derives one from a template: `{root}/{safe series title} ({start_year})`,
sanitizing the title component (no path separators, reserved device names, or trailing
dots/spaces) and creating the folder under that root.

You can override a series' path later, but the new path must resolve under a
registered root folder — an override pointing outside every root folder is rejected.
A valid path change renames the on-disk directory; if the rename fails, the path
change is rolled back so the database and disk never disagree.

## Series statistics

Series list and detail views report issue count, have/total issue-file counts, size on
disk, and next/last release dates. These are computed on the fly from the issue and
issue-file records each time they are requested — there are no stored counters to get
stale, and adding or removing a file is reflected immediately without a manual
"recount" action.

## Per-series rescan

A per-series rescan re-enumerates the files under the series' path: it clears issue-file
records for files that vanished from disk (returning those issues to Wanted), and
routes any newly-found, unmatched files through the shared import pipeline (see
`import.md` for how that pipeline works). Rescan runs automatically after
a metadata refresh and is also available on demand.

## Grouping series by franchise

A comic "series" in foragerr is one ComicVine **volume** — a single run. But a
franchise usually spans several runs over the years ("Batman (2011)", "Batman (2016)",
"Batman (2025)" are three volumes of one title). foragerr groups those runs into a
**franchise group** so you can see all of a title together.

Grouping is automatic and **display-only** — it never changes what a series is, how it
is monitored, or which issues are wanted. The group is derived from the series title:
foragerr strips a trailing volume year (`(2016)`) and `Vol N` designator and folds the
rest, so successive runs of the same title land in one group. A title with only one run
simply shows as itself.

The **Group volumes** toggle in the library index's Options menu switches between the
flat series list and the grouped view. What grouped looks like depends on the active
view mode: in **Posters**, a multi-volume franchise stacks into one card with a layered
shadow, an `N vols` chip, and owned/total summed across its runs; in **Overview** and
**Table**, a franchise becomes a collapsible header showing the title and a roll-up of
owned/total issues, with the runs nested beneath it. A franchise with only one run
always renders as an ordinary card/row, grouped or not. Either way the runs behave
exactly as they do in the flat view (same monitoring, same actions, same navigation).

If the automatic grouping gets something wrong, you can correct it from a group's ⋯
menu (the stacked card's footer, or the header in Overview/Table):

- **Rename** a group to give the franchise a different display name — the name sticks
  across future metadata refreshes.
- **Detach** a run from its group when it doesn't belong — the run is then left on its
  own, and a later refresh will not re-group it (your choice is locked). Clearing that
  choice later lets automatic grouping take over again.

## Collected editions (trades)

ComicVine models a collected edition — a trade paperback (TPB), graphic novel (GN), or
hardcover (HC) — as its own volume, so in foragerr a trade line is an ordinary series
of its own. foragerr **types** such a series from its title (it recognises "TPB",
"Graphic Novel", "Hardcover" and the like) and shows a small **TPB / GN / HC badge** on
the series card and its detail page, so collected editions are easy to tell apart from
single-issue runs. The library index's Filter menu has an **EDITIONS** section
(All editions / Collected only / Single issues only) that shows only collected
editions, only single-issue runs, or everything. If foragerr types a series wrong, you can set its
book-type explicitly when editing the series; your choice is kept across metadata
refreshes.

**Owning a trade never affects your single issues.** This is deliberate and guaranteed:
single issues and collected editions are independent tracks. Owning the "Saga" deluxe
hardcover does **not** mark any single "Saga" issue as owned, and does not remove a
missing single issue from your wanted/searchable list — a trade line's files belong to
the trade series, never to the single-issue series. Type a series as a collected
edition freely; it changes only how the series is labelled and named, never what is
wanted.

## The series detail screen

Clicking a series (from any library view, or quick search) opens its detail screen.

### Hero and actions

The hero shows the cover — full-size and, behind it, blurred and darkened as a
backdrop — over the series title, its book-type badge when typed as a collected
edition, and a meta row (monitored toggle, publisher, first-issue date, status,
issue count, and the file formats you own). Below that, an icon-over-label action
row dispatches the series' commands:

- **Search Monitored** — the ordinary series search, over monitored missing issues.
- **Search All** — searches for **every missing issue regardless of its monitored
  flag**; use it to fill gaps without first changing anything's monitored state.
- **Refresh** — re-pulls metadata from ComicVine and re-scans.
- **Edit** / **Delete** — see "Editing and deleting a series" below.
- **More (⋯)** — an overflow menu carrying **Rescan** (see "Per-series rescan"
  above) and **Rename Files** (opens the rename preview — see `web-ui.md`
  §Media Management), so no action loses reachability from the hero.

A long overview paragraph collapses behind a **Show more** toggle once it
overflows a few lines; a short overview shows no toggle at all.

### Issues tab

Below the hero, a bordered panel carries an `Issues · N / Collections · N` toggle
and a compact owned/total progress bar. The Issues tab is a dense table: a
selection checkbox, the per-issue monitored toggle, the verbatim issue number,
release date, a status pill (**Downloaded** when a file is present, **Missing**
once its release date has passed with no file, **Unreleased** otherwise), any
**collected-in** chips (see "Collections tab" below), file size, and per-row
automatic/interactive search actions.

**Bulk selection.** Click a row's checkbox to select it; **shift-click** another
row's checkbox to select every row in between (the last plain click sets the
anchor). The header checkbox selects or deselects every visible row. Selecting
one or more rows shows a labeled action bar above the table — **Monitor
selected**, **Unmonitor selected**, **Search selected** — replacing the
unlabeled header icon button older versions used. "Search selected" dispatches
one automatic-search command per selected issue, one after another (never in
parallel), so the command-status chip in the hero tracks progress as it goes
(e.g. "Search selected (2/5)"). The selection lives only on the screen — it
clears when you leave.

### Collections tab: declaring what a trade collects

foragerr does not scrape ComicVine's "collects" data (see "Collected editions
(trades)" above for why); instead **you** declare which single issues a trade
paperback, graphic novel, hardcover, or one-shot collects, and the Collections
tab both shows and edits those declarations.

What the tab shows depends on which kind of series you're viewing:

- **Viewing a collected edition (a trade-typed series)**: the tab lists that
  series' own issues — each one a physical collected book (e.g. "Volume 1",
  "Volume 2" as separate trades in the same run) — with a **Declare contents**
  button (or **Edit contents** once something is declared).
- **Viewing a single-issue series**: the tab lists every collected book, from
  any series in your library, that currently declares a range targeting it —
  read-only rows with **Open** (jump to that trade's own detail page) and
  **Edit**.

Either way an empty tab explains itself rather than showing a blank panel, and
the toggle's `Collections · N` count reflects exactly what's listed.

**Declaring a range.** Declare/Edit contents opens a dialog; when a
declaration already exists it opens pre-filled with every declared range, so
you edit what is really there:

1. Each range row has its own **target series** picker — any other series in
   your library (the trade series itself is excluded); a new row defaults to
   the previous row's target, so the common one-series case stays a single
   pick while an omnibus can mix targets.
2. Pick a **From** and **To** issue from that target's issue list — the
   inclusive range this collected book contains. Issue numbers show verbatim,
   exactly as the series lists them. If a pre-filled range's endpoints can no
   longer be resolved (the target's issues changed since it was declared),
   the row shows a warning and must be re-picked before saving.
3. **Add sub-range** for a non-contiguous collection (e.g. a book collecting
   #1–#6 and separately a bonus #8) — each sub-range is its own row,
   removable independently.
4. **Save** replaces the trade issue's *entire* declared set with what's in
   the dialog (the dialog says so) — with pre-fill, what you see is exactly
   what will be saved. **Delete all** clears every range for that trade
   issue.

Each declared range shows as a **"Collects #a–#b"** label (or **"#n"** for a
single issue) wherever it appears — on the Collections tab and as a
collected-in chip on the corresponding rows of the target series' Issues tab. A
**coverage pill** on each collected book reads the declared range against what
you actually own, computed live each time you look: **Collected** (every issue
in every declared range has a file), **Partial** (some do), or **Not
collected** (none do).

**This is display-only, on purpose.** Declaring or deleting a containment range
never changes any issue's monitored flag, never marks a single issue "owned,"
and never affects what gets searched for or downloaded — a missing single issue
stays wanted and searchable no matter what trades declare about it (the same
invariant that already keeps trades and singles independent tracks — see
"Collected editions (trades)" above). There is no automatic suggestion:
foragerr strips ComicVine's own "collects" links as untrusted content at
ingest, so every declaration you see here is one you made yourself.

## Editing and deleting a series

`PUT /api/v1/series/{id}` updates a series' monitored flag, monitor-new-items policy,
format profile, and root folder/path (subject to the same root-folder validation as
add). `DELETE /api/v1/series/{id}` removes a series and its issue/issue-file rows;
by default the files stay on disk. With `deleteFiles=true` the delete runs as a
background command (it serializes with imports/rescans and never blocks the
app): every file is first
moved to the recycle bin (permanently deleted only when no bin is configured —
see `import.md` §recycle bin), each recorded as a manual `file_deleted` history
event, and only then are the rows removed — a failure mid-way never leaves rows
gone while files were untouched. A single issue's file can likewise be deleted
from its row on the series detail screen (`DELETE /api/v1/issuefile/{id}`), with
the same bin routing; the issue returns to Wanted.
