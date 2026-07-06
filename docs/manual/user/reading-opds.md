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
`admin/configuration.md`.) No credentials are required in M1/M2: the catalog is
protected only by your tailnet — the same Tailscale-only exposure rule as the web
UI (`admin/network.md`). Do not expose the port beyond the tailnet.

## What the catalog looks like

- The **root** is a navigation feed listing only non-empty shelves — currently that is
  **All Series**.
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

Page-by-page streaming (reading without downloading the whole file first) is a
later milestone (`FRG-OPDS-008..012`); for now readers download whole files.
