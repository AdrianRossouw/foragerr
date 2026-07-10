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
`admin/configuration.md`.) No credentials are required, as foragerr currently has
no authentication: the catalog is
protected only by your tailnet — the same Tailscale-only exposure rule as the web
UI (`admin/network.md`). Do not expose the port beyond the tailnet.

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

- Streaming works for **`.cbz` (zip) comics**. A `.cbr` (rar) comic can still be
  **downloaded** whole, but it is not page-streamed (foragerr does not bundle an
  unrar tool); if you want streaming for a title, keep it as `.cbz`.
- Every issue also shows a **cover**: if there's no ComicVine cover on file,
  foragerr generates one from the comic's first page and serves it itself — so
  covers and thumbnails always appear, and your reader never has to reach out to a
  third-party image host to show them.
- Pages are served in natural reading order, and the reader can ask for a reduced
  width to save bandwidth. An operator can tune the streaming limits (see the
  `opds_pse_*` settings in `admin/configuration.md`); the defaults are fine for
  ordinary comics.
