# Sources

Sources connect an external store account to foragerr so items you already own
there show up in your library review queue on their own, instead of you moving
files across by hand. The model is generic — a connection lifecycle, an
inventory of owned items, and a review workflow — with one store implemented
today: **Humble Bundle** (`FRG-SRC-001`). It is the only store on the Sources
screen; more stores will appear here as they are built.

## Connecting Humble Bundle

foragerr authenticates to Humble the same way you'd stay logged in yourself —
by using your browser's own session cookie — rather than storing a password or
logging in on your behalf. foragerr never asks for your Humble password and
never automates a login (`FRG-SRC-002`):

1. Log into [humblebundle.com](https://www.humblebundle.com) in your own
   browser, as you normally would.
2. Get the session cookie onto your clipboard. The easy way is the **foragerr
   browser extension** (Chrome + Firefox): click it and press **Copy Humble
   session cookie** — one click, no developer tools. See the
   [extension README](../../../extension/README.md) for install and
   build/verify instructions. The extension only copies the cookie to your
   clipboard; it never talks to foragerr.
   *Fallback without the extension:* open your browser's developer tools, find
   the `_simpleauth_sess` cookie for `humblebundle.com`, and copy its value.
3. In foragerr, open **Sources → Humble Bundle** and paste the cookie into the
   connect card, then press **Connect**.

foragerr makes one live call to Humble's order API before it stores anything.
If the cookie is rejected — invalid, expired, or you copied the wrong value —
nothing is saved and the error tells you whether it looks like a bad cookie or
a network problem, so you know whether to re-copy it or just retry. If it's
accepted, the cookie is stored and the card reports **"Connected — N
orders"**, where N is your live Humble order count at the moment you
connected.

Once stored, the cookie never leaves the server again: every Sources screen
and every API response only ever show *whether* a cookie is configured, never
its value, the same write-only treatment every other stored credential in
foragerr gets. See `../admin/secrets.md` for how it's encrypted at rest, and
`docs/security/threat-model.md` / `docs/security/risk-register.md` for the
full analysis of what that credential can and can't do if it were ever
exposed.

## What sync does

Once connected, foragerr keeps your Humble entitlements up to date on its own:
a scheduled sync (the `source-sync` task, once a day by default) polls your
order history and compares it against what foragerr already knows about —
`FRG-SRC-003`. It shows up on **System → Tasks** with the same interval /
last-run / next-run display and the same **Run Now** force-run button every
other scheduled job has; you can also trigger **Sync now** on an individual
source at any time without waiting for the schedule.

Each purchased item is identified by its Humble order and product identity,
not its title, so a re-sync is always safe — it only adds new items or
refreshes display details on existing ones, never creates a duplicate and
never resets a decision you've already made about an item.

Humble bundles usually mix comics in with games, prose ebooks, and other
extras. Sync classifies every item automatically: comic-archive formats (CBZ,
CBR, CB7, CBT) are always recognized as comics, and a PDF offered on its own —
with no EPUB/MOBI/AZW3 edition alongside it — counts too, which covers
PDF-only original graphic novels and artbooks. Everything else (games, prose
ebooks with a PDF as just one of their formats, software) is classified as
**Other**. Only comics are shown by default; Other items are never discarded —
a **Show other items** toggle in the manage view reveals them, and if
something is ever misclassified you can still match or add it from there
(`FRG-SRC-003`).

## Review first — nothing downloads on its own

A newly discovered comic entitlement lands as **New**, with a proposed match
computed against **ComicVine's catalog** (`FRG-SRC-010`) — your library acts
as a shortcut overlay: a proposal already in your library is offered as a
one-click match, one that isn't is offered as a one-click add. Proposals are
honest: a candidate is only proposed when its title genuinely shares words
with the item's (no more coincidental lookalikes), and "no plausible match"
only describes the *automatic* verdict — every row also carries a live
**ComicVine search** (`FRG-UI-039`), the same search the Add Series screen
uses, so no row is ever a dead end. Pick a search result and it matches (if
you have it) or adds-and-matches (if you don't) in that single action.
Trade-shaped items ("… Vol. 4", collected editions) prefer the matching
collected-edition volume in their proposals rather than the single-issue
line.

By default nothing downloads and nothing in your library changes until you
act: **match**, **add**, **search-and-pick**, or **ignore** — each on a
single item or a bulk selection. An ignored item drops out of the pending
count and the default view but stays visible under the Ignored filter, and
**restore** returns it to New with its proposed match recomputed
(`FRG-SRC-004`).

### Working a big collection

Large accounts land thousands of items at once (the review list stays fast
at that scale — it renders only what's on screen). Three tools keep the work
proportional (`FRG-SRC-011`):

- **Groups**: three or more rows that are really the same title collapse
  into one expandable group with a count — a long run of mislabeled
  `"TITLE Vol. NNN"` singles reads as one line, not hundreds. A group
  header shows mixed statuses
  when its rows differ (including a failed-download callout), its checkbox
  selects the whole group, a shift-range across a collapsed group includes
  the rows folded inside it, and expanding always reaches every row's full
  actions — collapse is presentation, never a filter. The header also
  carries its own search/match picker, seeded with the group's title, so
  you can resolve the whole group without expanding it: picking a
  candidate already in your library matches every row in the group in one
  action, and picking one that isn't in your library yet adds it once and
  leaves the rest as proposals for a single bulk accept.
- **Bundles**: every row remembers which Humble bundle it came from, and
  the bulk bar can select a whole bundle at once — the natural unit for
  "this was an RPG bundle, ignore all of it".
- **Accept in bulk**: accepting a selection applies *each row's own
  proposal* server-side — mixed selections of matches and adds work in one
  action, failures are reported per row without stopping the rest, and a
  group of same-title adds converges cleanly (the first add turns its
  siblings into matches automatically, per `FRG-SRC-008`).

### Refreshing older proposals

Proposals computed by earlier versions (or while no ComicVine key was
configured) can be refreshed in bulk: **Recompute proposals** on the
source re-runs matching for items still awaiting review, in batches that
respect the ComicVine budget's background share — it stops cleanly if
the budget runs out and continues where it left off when run again.
Items you have already matched or ignored are never touched. When a path
budget is running hot, a compact meter appears above the review list;
the full per-path meter lives in Settings → General (`FRG-SRC-013`,
`FRG-UI-040`).

### Publisher filtering

Some bundle items aren't comics no matter their file format — RPG
rulebooks, tech-book PDFs, art books — and format detection alone can't
always tell them apart. Listing a publisher classifies its items as Other
at sync time, and that list lives in one place, library-wide, applying to
every connected source: **Settings → General**, beside the ComicVine
publisher ignore list (`FRG-SRC-012`) — not here on the Sources screen. See
`../admin/configuration.md` for the setting, its shipped defaults, and how
it behaves.

Proposals stay honest as your library changes underneath them (`FRG-SRC-008`).
Humble bundles routinely contain many items from the same series, all
proposing the same "add" — acting on one used to strand the rest. Now, adding
from one row converts its siblings' proposals into "match to the series you
just added", so each remaining row is a single successful click; and pressing
**add** on something that turns out to already be in your library quietly
becomes a match to the existing series instead of an error.

That sweep isn't limited to the add path. Picking a series for one row — a
plain match to an in-library series works just as well as an add — now
re-proposes its still-`New` same-group siblings within that source to the
series you picked (`FRG-SRC-014`), so a single search-and-pick on one row
fills in the rest of its group instead of leaving them stale. It writes
proposals only: a swept sibling still shows as New and needs its own accept,
and anything you've already matched or ignored is left exactly as it was.

### The Auto-sync toggle

Each source has its own **Auto-sync new purchases** toggle, and it **ships
off**. Leave it off — the default — and every new comic entitlement waits for
your review, no matter how confident its proposed match is. Turn it on and a
confidently-matched new item is accepted and downloaded automatically the next
time sync runs; anything below the confidence threshold still waits in review
either way, toggle or not. This is the same deliberately opt-in posture
foragerr takes with the built-in GetComics downloader (see `downloads.md`):
unattended acquisition is something you turn on, never something that happens
by default.

### Collected editions and issues you already own

When you match a collected edition, foragerr works out exactly which tracked
single issues it fills and never suppresses or double-counts an issue you
already own as a single file — the same invariant that governs trade
containment elsewhere in the library (`FRG-SRC-007`). An issue already owned
as a single stays exactly as it is; only the gaps the edition actually fills
get marked owned. An entitlement with no matching single issues at all — an
original graphic novel or artbook — is added as a standalone item instead of
inventing issue records that don't exist.

## When a session expires

A Humble session cookie doesn't last forever. If a sync ever gets an
authentication failure from Humble mid-run, foragerr doesn't retry against the
dead session or crash the scheduler (`FRG-SRC-005`): the source flips to
**Expired**, that sync's already-fetched results are kept, a banner appears
across the app naming the affected source, and its entry turns amber in the
health footer and on the System → Health screen with a reconnect hint. No
further Humble traffic happens until you act.

To resume, paste a fresh cookie the same way you connected the first time —
foragerr validates it live and, on success, the source returns to Connected,
the banner and health warning clear, and the next scheduled sync runs
normally.

Nothing about expiry — or a deliberate **Disconnect** — ever touches your
library. Disconnecting deletes the stored cookie but keeps every entitlement
you've reviewed and every file already imported exactly as it is; the only
thing that stops is future syncing (`FRG-SRC-001`). The same is true while a
source sits Expired: sync pauses, nothing already synced or imported is
removed or degraded.

## Downloading and importing

Accepting a matched entitlement fetches it from Humble and hands it to the
same import pipeline every other acquisition path uses (`FRG-SRC-006`): the
download is verified against the checksum Humble's API reports before it's
imported, so a corrupted or mismatched transfer is caught and never lands in
your library. A failed or mismatched download is recorded on the
entitlement's own row on the Sources screen — with the reason and an explicit
**Retry** button that re-queues the download (`FRG-SRC-009`) — rather than in
the indexer/usenet failed-downloads list, because there is nothing to
blocklist or re-search for content you already own. Failed source downloads
also surface in application health: a source with failed downloads turns
amber on System → Health with the failed count and a pointer back to its
review screen, so a failure can't sit invisible until the next time you open
Sources. A successful download imports exactly like a completed indexer grab,
and the entitlement shows as matched with its issues owned.

Because the file arrived from an entitlement you matched yourself, import
trusts that decision (`FRG-PP-021`): the series is already settled, and only
the issue number is read from Humble's often-chaotic filenames — including
the `Vol. N`-that-means-issue-N idiom (`FRG-PP-022`). See `import.md` for the
details.

See `../admin/secrets.md` for how the Humble cookie is protected at rest, and
`../admin/configuration.md` for the sync interval and request-spacing
settings.
