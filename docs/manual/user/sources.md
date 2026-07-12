# Sources

Sources connect an external store account to foragerr so items you already own
there show up in your library review queue on their own, instead of you moving
files across by hand. The model is generic — a connection lifecycle, an
inventory of owned items, and a review workflow — with one store implemented
today: **Humble Bundle** (`FRG-SRC-001`). Other tabs on the Sources screen may
appear as placeholders for stores foragerr doesn't connect to yet; only Humble
Bundle is connectable.

## Connecting Humble Bundle

foragerr authenticates to Humble the same way you'd stay logged in yourself —
by using your browser's own session cookie — rather than storing a password or
logging in on your behalf. foragerr never asks for your Humble password and
never automates a login (`FRG-SRC-002`):

1. Log into [humblebundle.com](https://www.humblebundle.com) in your own
   browser, as you normally would.
2. Open your browser's developer tools, find the `_simpleauth_sess` cookie for
   `humblebundle.com`, and copy its value.
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
against your existing library computed for you. By default nothing downloads
and nothing in your library changes until you act on it: **match** it to a
series, **add** it as something new, or **ignore** it — each action works on a
single item or a bulk selection. An ignored item drops out of the pending
count and the default view but stays visible under the Ignored filter, and
**restore** returns it to New with its proposed match recomputed
(`FRG-SRC-004`).

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
your library — it appears in the same failed-download surface as any other
download, with retry available. A successful download imports exactly like a
completed indexer grab, and the entitlement shows as matched with its issues
owned.

See `../admin/secrets.md` for how the Humble cookie is protected at rest, and
`../admin/configuration.md` for the sync interval and request-spacing
settings.
