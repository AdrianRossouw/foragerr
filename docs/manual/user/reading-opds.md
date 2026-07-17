# Reading over OPDS

foragerr has no built-in reader — by design. Instead it serves an **OPDS 1.2
catalog** that any OPDS-capable reading app can browse and download from. On an
iPad, apps like Panels, Chunky, or KyBook read OPDS natively.

## Connecting a reader

Point your reading app at:

```
http://<your-tailnet-address>:8789/opds
```

(The `/opds` base path is configurable — `FORAGERR_OPDS_BASE_PATH`; see
`admin/configuration.md`.) The catalog requires a credential like every other
surface: sign in with the operator username and the OPDS password (set by
your administrator — it's the admin password unless a separate
`FORAGERR_OPDS_PASSWORD` was configured; see `admin/authentication.md`). Most
reading apps, including Panels, Chunky, and KyBook, prompt for username and
password the first time they connect to an OPDS catalog and store the
credential themselves, so this is normally a one-time step per device. A bare
request without credentials gets a `401` challenge, which is what triggers
that prompt. The tailnet remains the recommended exposure boundary regardless
— see `admin/network.md` — do not expose the port beyond it.

## What the catalog looks like

- The **root** is a navigation feed listing only non-empty shelves — **All
  Series** and **Recent Additions**.
- **Recent Additions** lists the most recently imported issues, newest first by
  import time (not release date) — pick up this week's haul without hunting
  through series shelves. Entries are full acquisition entries; download
  directly from the feed.
- The root also advertises **search**: readers that support OpenSearch (Panels,
  Chunky, ...) can search the catalog by series title from inside the app; the
  results feed navigates into each matched series' shelf.
- Each series is an **acquisition feed** of its downloadable issues, built
  entirely from foragerr's database: series and issue metadata, file sizes, and
  cover thumbnails from the local cover cache. foragerr never opens an archive to
  serve a feed, so browsing is always fast, even for large libraries.
- Long shelves are **paginated** with standard next/previous links and OpenSearch
  totals, so readers can show progress through the catalog.
- The **All Series** shelf mirrors your full library by default — including
  series you subscribe to that have no files yet (they open as empty shelves
  until their first file imports). If you would rather browse only shelves
  that contain something to read, set `opds_hide_fileless_series` to true
  (`configuration.md`); hidden series stay findable via OPDS search either way.
- Every feed, file, and page URL answers **HEAD** requests as well as GET, so
  reader apps and proxies that preflight a URL with HEAD see the catalog exactly
  as they would with GET (same status, auth challenge, and headers). No setup
  needed — it just works with clients that behave this way.

## Downloads

Downloading an issue streams the original file with its correct comic media type
(`application/vnd.comicbook+zip` for cbz, `application/vnd.comicbook-rar` for
cbr), so readers recognize the format immediately. Files are addressed **only by
library id** — the catalog never accepts a file path from the client, and every
download is confinement-checked against your registered root folders before a
byte is served. An id that resolves outside the library simply returns "not
found".

## Page streaming (read without downloading the whole file)

Readers that support the **OPDS Page Streaming Extension (OPDS-PSE)** — Panels and
Chunky among them — can open a comic and stream it **one page at a time** instead of
downloading the whole `.cbz` first. It opens faster and is lighter on a big issue,
and it is what those readers use by default when they see the option.

You don't configure anything: every issue entry advertises **both** page streaming
and whole-file download, so your reader picks whichever it supports — a
non-streaming reader just downloads the file as before, nothing changes for it.

A few things worth knowing:

- Streaming works for **`.cbz` (zip) and `.cbr` (rar) comics** alike — the Docker
  image bundles a RAR extraction tool, so your whole library streams regardless of
  container. A `.cbr` imported before this support streams too: its page count is
  computed the first time a reader opens it, no re-import needed. Only an
  **encrypted or damaged** archive falls back to download-only. PDFs remain
  download-only (readers like Panels open a downloaded PDF fine; page streaming is
  a comic-archive feature).
- If you prefer a uniform zip library, an **opt-in** setting converts `.cbr` to
  `.cbz` at import time (off by default; the converted file is verified before the
  original is removed) — see `convert_cbr_to_cbz` in `admin/configuration.md`.
  On-demand conversion is also available per series and per issue.
- Every issue shows **its own cover** — the comic's first page, which is that
  issue's actual cover, so each issue in a series looks distinct and matches
  what it opens to. The **shelf** shows one cover per series (the cached
  ComicVine volume cover, when there is one). All covers are served by foragerr
  over the same OPDS login your reader already uses, so they always appear and
  your reader never reaches out to a third-party image host — nor to any
  endpoint it isn't authenticated for.
- Pages are served in natural reading order, and the reader can ask for a reduced
  width to save bandwidth. An operator can tune the streaming limits (see the
  `opds_pse_*` settings in `admin/configuration.md`); the defaults are fine for
  ordinary comics.
