# Import & renaming

Import is how a comic file becomes part of your library: foragerr verifies the file,
works out which series and issue it is, decides whether it belongs in the library,
and — only if every check passes — renames it into the right series folder and
records it against the issue. One shared pipeline does this for every source: a
completed download and a per-series rescan go through exactly the same evidence
gathering, the same decision rules, and the same file handling. (Manual import — 
pointing foragerr at an arbitrary folder and resolving matches by hand — is planned
for M2 and will reuse this same pipeline.)

## Completed downloads

About once a minute, foragerr processes downloads that have finished and been
verified (see `downloads.md`). For each one it:

1. **Reconciles** the finished item back to the grab that produced it, by download
   ID. If that record is missing, it falls back to parsing the release name — and a
   foragerr-generated filename carries an embedded `[__issueid__]` tag that maps the
   file straight to its issue.
2. **Gathers evidence** about what the file is. Every naming layer is parsed by the
   same filename parser used everywhere else: the file name, the folder name, the
   download client's item title, and the original grab record. Layers are merged in
   confidence order (grab record first, embedded issue-id tag next, then file name,
   folder, client title), and each resolved field remembers which layer it came
   from, so an odd match is diagnosable.
3. **Decides** whether to import. The decision rules run in order and record their
   reasons: the file must map to a known series and issue; the archive must be
   structurally valid (see below); it must not look like a sample/junk file; the
   destination volume must have enough free space (with a safety margin); the issue
   must not already have this file; and if the issue already has a *different*
   file, the new one must be an upgrade under your profile — an equal-or-worse file
   is blocked as "not an upgrade".
4. **Executes** the import: the file is renamed according to your naming template
   and moved into the series folder, the issue gains a file record, the download is
   marked imported, and — only after all of that succeeded, and only if the client's
   "remove completed downloads" setting allows — the item is cleaned up from the
   download client. Files are never removed from a client before the import has
   actually succeeded.

### Blocked imports are never lost

Anything that cannot be imported is marked **import-blocked**, kept, and shown in
the queue with the exact reasons (e.g. "matched no issue", "archive is
password-protected", "not an upgrade over the existing file"). Nothing is ever
auto-deleted. A blocked item is retried automatically whenever its evidence changes
— fix the cause (add the series, free up disk space, remove the better file) and
the next processing cycle picks it up again. A permanently stuck item stays visibly
blocked until you resolve or remove it.

### Upgrades and the quarantine folder

When an import replaces an issue's existing file (an upgrade), the replaced file is
**moved to `<config>/quarantine/<date>/`, never deleted**. This is M1's stand-in
for a recycle bin (a fuller recycle-bin feature is planned for M2). If an upgrade
turns out to be a mistake, the previous file is sitting in quarantine, and its
location is recorded on the issue's history event.

## Archive safety checks

Every candidate file is structurally verified before it can enter the library —
without ever being extracted:

- The file's magic bytes must match a supported comic container (zip/cbz, rar/cbr,
  7z/cb7). An HTML error page saved as `.cbz` fails here.
- A cbz must be a valid zip archive containing at least one image entry, must not
  be password-protected, and must respect safety limits (member count, per-member
  and total declared uncompressed size, no archive-inside-archive). Member names
  that try to escape their folder (absolute paths, `..` sequences) and symlink
  entries are rejected outright.
- A cbr is checked against the same rules when RAR listing support is available;
  otherwise it is validated by its RAR signature. A cb7 is validated by signature
  in M1.

A corrupt or password-protected download fails the pipeline and feeds the standard
failed-download handling: the release is blocklisted and, if auto-redownload is on,
a replacement search is queued immediately (`downloads.md`).

## Renaming

Imported files are named by a token template. The M1 default is:

```
{Series Title} {Issue Number:000} ({Year}) [__{IssueId}__]
```

which produces names like `Saga 001 (2012) [__4050-12345__].cbz`. Available tokens
include `{Series Title}`, `{Issue Number}` (with zero-padding control:
`{Issue Number:000}` renders issue 5 as `005`, and decimal issues like `5.1` pad
only the integer part), `{Year}`, `{Volume}`, `{Publisher}`, `{Issue Title}`,
`{Release Group}`, `{Classification}`, `{Booktype}`, and `{IssueId}`. Optional
groups in `(...)` / `[...]` drop out cleanly when their tokens have no value — a
series with no known year simply omits the `(Year)` part rather than rendering
`()`.

Series folders are created from a folder template (default
`{Series Title} ({Year})`, matching how the library organized folders before this
change). Characters that are illegal in filenames are replaced, names are kept
within filesystem length limits, and every constructed path is confined to your
library's root folder — a hostile or bizarre metadata title cannot cause a file to
be written outside the library.

**The round-trip guarantee:** every name foragerr renders is required to parse back
to the same series and issue through its own filename parser. This is enforced by
tests across the whole parser corpus, so renaming can never produce a file that
foragerr would later fail to recognize. The `[__{IssueId}__]` tag in the default
template makes re-recognition exact even if a series is later retitled.

### Safe file handling

File moves are designed so that no partial file is ever visible at a final library
path and the source is never deleted until the destination is verified. Same-device
moves are atomic; cross-device moves copy to a hidden temporary name in the
destination folder, flush to disk, verify the size, promote atomically, and only
then remove the source. Free space (file size plus a margin) is checked before any
bytes move. After a successful move, emptied source folders are cleaned up (ignoring
junk like `.DS_Store`), stopping safely below the download/staging root.

## Rescanning a series

A per-series rescan walks the series folder on disk and routes every comic file it
finds through this same pipeline: files already tracked are skipped, new files are
matched and imported, and anything unmatched or rejected is recorded as
import-blocked on a rescan report with its reasons — the same
blocked-not-lost guarantee as downloads. A rescan never runs concurrently with
download import processing, so the two can never fight over the same files.

## Import history

Every step is recorded as history: grabbed, imported, import-failed,
import-blocked, and upgrade-replaced events, joined by download ID and issue. The
history browsing UI arrives in M2; the events are being recorded now, so history
will be complete retroactively.
