# Search & indexers

foragerr searches Newznab-protocol usenet indexers (e.g. DogNZB, NZB.su) for comic
releases. Every candidate release, from whichever path found it, is evaluated by one
shared decision engine so behavior and reasoning are consistent everywhere.

## Configuring an indexer

Each indexer is a row: name, implementation (`newznab`), base URL, API key, priority
(default 25), an enabled flag, and three independent usage toggles — enable RSS,
enable automatic search, enable interactive search. A fetch path only ever queries
indexers whose matching toggle is on; the toggles are independent of each other (an
indexer can serve interactive search without serving automatic search, for example).

`GET /api/v1/indexer/schema` returns field metadata for rendering an indexer's
settings form; `POST /api/v1/indexer/test` runs a live capabilities probe (`?t=caps`)
against the configured indexer and reports a field-precise failure (e.g. wrong API
key) before you save it as enabled. API keys are held as redacted secrets and never
appear verbatim in logs.

Indexer capabilities (`?t=caps`) are cached for about 7 days and drive which
categories are offered — defaulting to 7030 (Books/Comics) with a conservative
fallback if an indexer's caps response doesn't mention it.

## How a search works

Because comics are searchable on Newznab only by free-text `q=` (there's no
comic-specific id-based search), a query for "Batman" issue 5 escalates through a
ladder of increasingly specific queries (padded issue-number variants, volume-tagged,
year-tagged) and every result is evaluated — including results that look plausible but
are actually wrong. The decision engine explicitly checks that a result maps to the
series and issue you actually searched for, not just a substring match — a search for
"Batman" that turns up "Batman Beyond", or a "wrong issue" caused by a year in the
title being misread as an issue number, is rejected with a specific reason rather than
grabbed.

## Reading a decision

Every candidate release runs through the full set of accept/reject checks — the engine
does not stop at the first failure, so you see every reason a release was rejected,
not just the first one. A release's outcome is one of:

- **Approved** — passed everything.
- **Rejected** — failed at least one permanent check (e.g. blocklisted, wrong
  format, size out of bounds).
- **Temporarily rejected** — failed only checks that are inherently temporary (e.g.
  minimum release age, indexer currently in back-off); it may still be picked up on a
  later pass.

Checks include: format allowed by the series' quality profile; whether the release is
a genuine upgrade over the file already on disk; per-format and global size bounds;
usenet retention age; must-contain/must-not-contain terms; already queued or already
imported; blocklisted; and indexer currently backed off.

Among approved candidates for the same issue, foragerr picks the best one using an
ordered comparator chain: format-profile rung first, then preferred-term/release-group
score, then indexer priority, then release age (bucketed so a few hours' difference
doesn't dominate), then closeness to your preferred size.

## Add New: hidden publishers

Adding a series searches ComicVine, whose catalogue is full of foreign-market
reprints — a search for a current Marvel or DC title often surfaces German,
Spanish or French reprint editions above the original-language volume. foragerr
hides results from a configurable list of reprint publishers
(`comicvine_ignored_publishers`, editable in **Settings → General**) so the
volume you actually want ranks first. Nothing is dropped silently: when a search
hides results the Add New screen shows a line — "N result(s) hidden by your
publisher ignore list — Show" — and clicking **Show** reveals them for that
search, each marked with an *Ignored* badge, alongside a link to edit the list.
The reveal is per-search and never changes the stored list. New installs start
with a conservative default list; existing installs keep whatever they had (see
`../admin/configuration.md`).

## Interactive search

An interactive search runs live against interactive-enabled indexers and returns every
decision — approved, temporarily rejected, and rejected — each with its full list of
reasons, sorted best-first. Results are cached server-side for about 30 minutes,
keyed by indexer + release guid; grabbing a result from that list uses the cached
decision. If you try to grab after the cache has expired, you get a clear "search
again" error rather than a silent, possibly-stale re-search.

## Automatic search

foragerr runs automatic search as commands, not a background poll you configure
directly: a single-issue search, a whole-series missing-issues search, and a
cutoff-unmet search, each triggered after a series is added (if you asked for
search-on-add), after a failed download, or on demand. An automatic search command
queries every automatic-search-enabled indexer, evaluates results through the same
decision engine, and grabs the best approved release per issue.

## De-duplication

Results appearing more than once from a single indexer are collapsed by release guid.
Results for the same content across two different indexers are also de-duplicated,
keeping the copy from the higher-priority indexer.
