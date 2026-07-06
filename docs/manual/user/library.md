# Library & series management

foragerr tracks comic series the same way Sonarr tracks TV series: you add a series
from ComicVine, it becomes part of your library, and foragerr keeps its issue list and
on-disk files in sync going forward.

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

## Editing and deleting a series

`PUT /api/v1/series/{id}` updates a series' monitored flag, monitor-new-items policy,
format profile, and root folder/path (subject to the same root-folder validation as
add). `DELETE /api/v1/series/{id}` removes a series and its issue/issue-file rows;
by default the files stay on disk. Deleting the series **and** its files
(`deleteFiles=true`) is explicitly not supported yet — that request returns
`501 Not Implemented`.
