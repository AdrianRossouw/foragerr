# Mylar3 OPDS Server — Research Findings

Scope: `mylar/opds.py`, its CherryPy wiring, the Mako feed template, and image
helpers in the vendored reference at `/Users/adrian/Projects/foragerr/.reference/mylar3`.
All citations are `file:line` against that tree. This is read-only research for
foragerr's own (future) OPDS server; no repo files were modified.

Key files:
- `mylar/opds.py` — the whole OPDS implementation (single `OPDS` class, 976 lines)
- `mylar/webserve.py:7683-7695` — the exposed `opds()` CherryPy handler
- `mylar/webstart.py:157-168` — OPDS auth / mount configuration
- `data/interfaces/default/opds.html` — the Mako template that renders every feed
- `mylar/getimage.py` — archive open, page listing, image scaling
- `mylar/config.py:442-448` — OPDS config keys and defaults

---

## 1. OPDS version/profile, feed hierarchy, URLs, pagination

**Profile.** OPDS 1.x (Atom-based, "OPDS Catalog 1.x"). Every navigation link
carries `type="application/atom+xml; profile=opds-catalog; kind=navigation"` and
acquisition entries use `rel="http://opds-spec.org/acquisition"`
(`opds.html:43`, `opds.py:137-138`). The template declares the standard namespaces:
Atom, `opds` (`http://opds-spec.org/2010/catalog`), OpenSearch 1.1, Dublin Core
terms, and the PSE namespace `http://vaemendis.net/opds-pse/ns`
(`opds.html:1-8`). There is **no OPDS 2.0 / JSON** support — it is XML only.

**Single endpoint, `cmd`-dispatched.** Everything hangs off one URL
(`/opds` by default, `OPDS_ENDPOINT`, `config.py:444`), and the operation is chosen
by a `cmd` query parameter. `webserve.py:7683` exposes `opds(*args, **kwargs)`,
which instantiates `OPDS`, calls `checkParams` (validates `cmd` against a
whitelist) then `fetchData` (dispatches to `_<cmd>`), `opds.py:63-108`. Whitelisted
commands (`opds.py:39`):
`root, Publishers, AllTitles, StoryArcs, ReadList, OneOffs, Comic, Publisher,
Issue, Stream, StoryArc, Recent, deliverFile`.

**Feed hierarchy.**
- **Root / navigation** (`_root`, `opds.py:128-227`): a navigation feed whose
  entries are the top-level shelves — Recent Additions, Publishers (count),
  All Titles (count), Story Arcs (count), Read List (count), One-Offs (count).
  Entries are only added when the underlying data is non-empty. Root also emits
  `start`, `self`, and a `search` link (see §4/§5).
- **Navigation feeds**: `_Publishers` (list of publishers), `_AllTitles`
  (list of series), `_StoryArcs` (list of arcs). Each publisher/series/arc entry
  points to a deeper feed.
- **Acquisition feeds**: `_Comic` (issues in a series), `_Publisher`
  (series for a publisher — actually navigation to series), `_Recent`,
  `_ReadList`, `_StoryArc`, `_OneOffs`. These contain the downloadable entries.

**URL structure** (all relative to `opdsroot`, which is `HTTP_ROOT + OPDS_ENDPOINT`,
`opds.py:53-61`):
- `?cmd=Publishers[&index=N]`
- `?cmd=Publisher&pubid=<publisher>[&index=N]`
- `?cmd=AllTitles[&index=N]`
- `?cmd=Comic&comicid=<id>[&index=N]`
- `?cmd=StoryArcs` / `?cmd=StoryArc&arcid=<id>`
- `?cmd=Recent[&index=N]`
- `?cmd=ReadList` / `?cmd=OneOffs`
- Download: `?cmd=Issue&issueid=<id>&file=<location>`
- Stream (PSE): `?cmd=Stream&issueid=<id>&file=<location>&page=<n>&width=<w>`
- One-off download: `?cmd=deliverFile&file=<path>&filename=<name>`

**Pagination.** Offset-based via an `index` query param and a fixed page size
`OPDS_PAGESIZE` (default **30**, `config.py:448`; read into `self.PAGE_SIZE`,
`opds.py:46`). Feeds emit Atom `rel="next"` / `rel="previous"` links computed from
`index ± PAGE_SIZE` and slice the entry list `entries[index:index+PAGE_SIZE]`
(e.g. `opds.py:264-272`). There is **no `rel="first"`/`rel="last"` and no
`opensearch:totalResults`/`itemsPerPage`** in the feeds, so clients cannot show
absolute progress. Note the pattern is inconsistent: some acquisition feeds
(`_Comic`, `_Recent`, `_ReadList`, `_StoryArc`) build the *full* entry list in
memory (opening every archive) and only the navigation feeds actually slice — see
§5 for the performance and copy-paste-bug consequences.

---

## 2. How comics are served (download vs streaming), MIME types, covers

Two distinct delivery paths:

**(a) Whole-file download** — `_Issue` (`opds.py:601-627`). Given `issueid`, it
looks the issue up in `storyarcs`, then `issues`, then `annuals`, resolves the real
path as `ComicLocation + Location` from the DB, and sets `self.file` /
`self.filename`. `fetchData` then calls CherryPy's
`serve_download(path=self.file, name=self.filename)` (`opds.py:101`), i.e. the raw
`.cbz`/`.cbr` is streamed to the client as an attachment. The template advertises
these as `type="application/octet-stream"` with `rel=".../acquisition"`
(`opds.html:43-44`) — **not** the more specific `application/x-cbz`/`x-cbr` types.
As a side effect of a successful `Issue` fetch, the issue is marked read in the
reading list (`opds.py:95-100`).

**(b) OPDS-PSE page streaming — YES, supported.** `_Stream` (`opds.py:550-598`)
implements the OPDS Page Streaming Extension 1.0
(`https://vaemendis.net/opds-pse/`, cited in the code comment `opds.py:551`). It
resolves the file via `_Issue`, opens the archive, lists image pages, bounds-checks
`page`, and returns the single requested page image. Each acquisition entry that is
a real file also carries a `pse_count` and a `stream` URL; the template emits a PSE
link (`opds.html:53-59`):

```
<link href="...&page={pageNumber}&width={maxWidth}"
      rel="http://vaemendis.net/opds-pse/stream"
      type="image/jpeg" pse:count="N"/>
```

Optional `width` triggers server-side downscaling to JPEG via
`scale_image` (`opds.py:583-595`, `getimage.py:66-82`); without `width` the raw
page bytes are returned with a content-type derived from the file extension
(`opds.py:598`). Images are streamed with `serve_fileobj(..., content_type='image/'+iformat)`
(`opds.py:88-93`). `pse:count` is computed by actually opening the archive and
counting image members (`page_count`/`comic_pages`, `getimage.py:60-64`) — this is
done for **every entry at feed-render time**, not lazily (see §5).

Archive support (`getimage.py:41-61`): `.cbz` via `zipfile`, otherwise `rarfile`
(with a "zip renamed as rar" fallback). Page images recognised by extension:
jpg/jpeg/png/webp (`getimage.py:57-58`); pages are returned in `sorted(namelist())`
order (`getimage.py:60-61`) — naive lexical sort, no natural/numeric ordering.

**Covers/thumbnails.** For issue entries, the feed does **not** generate covers
from the archive. It reuses ComicVine image URLs already stored in the DB:
`thumbnail = issue['ImageURL']`, `image = issue['ImageURL_ALT']`
(`opds.py:393-394`, `470-480`), emitted as `rel="http://opds-spec.org/image/thumbnail"`
and `.../image` links (`opds.html:61-74`). These point at remote CV URLs
(or Mylar's cached copies), so cover display depends on the client being able to
reach them and on `OPDS_METAINFO`-independent DB fields. One-offs and many story-arc
/ annual entries have `image=None`/`thumbnail=None` (no cover at all). `getimage.py`
*can* extract a cover from the archive (`extract_image`) and resize to JPEG, but the
OPDS path does not use it for feed thumbnails.

**Metadata.** When `OPDS_METAINFO` is enabled (default **False**, `config.py:447`),
each file entry is opened and `helpers.IssueDetails(fileloc)` reads embedded
ComicInfo.xml to populate `author` (writer) and `content` (summary)
(`opds.py:403-408`, `489-496`). With it off, author/summary are empty.

---

## 3. Auth model on OPDS endpoints

**HTTP Basic, optional, off by default, configured independently of the main UI.**
`webstart.py:157-168`:

- If `OPDS_AUTHENTICATION` (default **False**, `config.py:443`) is on, the `/opds`
  branch mounts `tools.auth_basic.on = True` with realm `"Mylar OPDS"` and a
  password dict built from `OPDS_USERNAME`/`OPDS_PASSWORD`, plus the main
  `http_username`/`http_password` if different (`webstart.py:158-166`).
- If it is **off**, `/opds` is mounted with `tools.auth_basic.on = False` **and**
  `tools.auth.on = False` (`webstart.py:168`) — i.e. OPDS is explicitly exempted
  from the session/forms auth that protects the rest of the site. **So with the
  default config, OPDS is world-readable even when the main UI requires login.**
- Credentials are checked with CherryPy's `checkpassword_dict` — plaintext
  comparison, Basic auth base64 only (no digest, no TLS enforced by the app).
- There is **no API-key-in-URL** scheme for OPDS (the general Mylar REST API uses
  `apikey`, but OPDS does not). Auth is entirely HTTP Basic or nothing.

For foragerr's Tailscale deployment this matters: network-layer auth (Tailscale ACLs)
would be the real gate; app-layer OPDS auth is optional and weak.

---

## 4. Client quirks accommodated

- **OPDS-PSE** (`vaemendis.net`) — the de-facto page-streaming extension used by
  Chunky, KyBook, Panels, etc. The `{pageNumber}` / `{maxWidth}` URI templates and
  `pse:count` are exactly what those readers expect (`opds.html:53-59`).
- **OpenSearch** — root advertises a search link
  `type="application/opensearchdescription+xml"` (`opds.py:139`) and the template
  declares the OpenSearch namespace (`opds.html:5`). **However this is broken** —
  see §5; there is no descriptor document and no search handler.
- **Cover/thumbnail split** — both `.../image` (full) and `.../image/thumbnail`
  links are emitted so clients that want a small cover get one (`opds.html:61-74`).
- **`author` and `content`/summary** — populated from embedded ComicInfo when
  `OPDS_METAINFO` is on, which readers show in the book detail view.
- **`updated` timestamps** per entry (DateAdded / ReleaseDate fallback) so clients
  can sort/detect new items.
- **octet-stream acquisition type** — deliberately generic so any reader will accept
  the download, at the cost of not signalling cbz/cbr specifically.

No evidence in the code or `README`/`API_REFERENCE` about **what Panels or Chunky
specifically require** beyond standard OPDS+PSE. I did not find client-specific
user-agent branching. **Uncertainty flagged:** whether current Panels/Chunky builds
prefer OPDS-PSE vs. whole-file download, and whether they need OPDS 2.0, cannot be
determined from this codebase — that must be verified against those apps' own docs,
not inferred here.

---

## 5. Weaknesses and security observations (for threat analysis)

**Security**

- **S1 — Arbitrary file read via `deliverFile` (path traversal).** `_deliverFile`
  (`opds.py:537-547`) takes the `file` kwarg and assigns it *directly* to
  `self.file` with no validation, containment check, or base-directory join
  (`self.file = str(kwargs['file'])`), then `serve_download` serves it. The
  One-Offs feed builds these links from `GRABBAG_DIR` glob results, but the
  endpoint accepts any client-supplied absolute path. Combined with default
  `OPDS_AUTHENTICATION = False`, an unauthenticated client can request
  `?cmd=deliverFile&file=/etc/passwd&filename=x` and read arbitrary files
  readable by the Mylar process. **This is the headline finding.**
- **S2 — OPDS unauthenticated by default and explicitly exempted from site auth**
  (`webstart.py:168`, `config.py:443`). Even users who enable the main login get an
  open OPDS unless they *separately* enable OPDS auth.
- **S3 — SQL built by string concatenation.** `_Comic`, `_StoryArc` interpolate
  `comicid`/`arcid` straight into SQL (`opds.py:374-376`, `856`):
  `'SELECT * from issues WHERE ComicID="' + kwargs['comicid'] + '"...'`. These are
  client-controlled query params → SQL injection surface. (Most other queries use
  bound `?` params, so this is an inconsistency, not a blanket practice.)
- **S4 — Weak auth primitives.** Plaintext-compared HTTP Basic, no TLS requirement,
  no rate limiting, no lockout. Fine only behind Tailscale.
- **S5 — Server-side archive opening on untrusted paths / zip-bomb & decompression
  exposure.** `_Stream` and feed rendering open arbitrary archives and (with
  `width`) decompress/resize images with PIL (`ImageFile.LOAD_TRUNCATED_IMAGES=True`,
  `getimage.py:26`) — resource-exhaustion / malformed-image surface.

**Correctness / robustness**

- **W1 — Search is advertised but not implemented.** Root emits a `?cmd=search`
  OpenSearch link (`opds.py:139`) but `search` is **not** in `cmd_list`
  (`opds.py:39`) and there is no `_search` method, so following it yields
  `Unknown command: search` (`opds.py:74-75`). No OpenSearch *descriptor document*
  is served either.
- **W2 — Pagination copy-paste bugs.** `_Publishers` and `_Publisher` next/prev
  links point at `cmd=AllTitles` instead of `cmd=Publishers`/`cmd=Publisher`
  (`opds.py:266,269`), and several `previous` links use `cmd=Read`
  (nonexistent command) instead of `cmd=ReadList`/etc. (`opds.py:741,838`).
- **W3 — Whole-list-in-memory + open-every-archive.** Acquisition feeds compute
  `pse_count` by opening every issue's archive at render time
  (`opds.py:409-414, 497-502, 804-809, 923-928`) and build the entire entry list
  before slicing, so a large series/read-list makes one feed request do N archive
  opens and N `os.path.isfile` stats — slow and I/O heavy over a remote link.
- **W4 — No total-count / progress metadata** (no `opensearch:totalResults`,
  no `rel=first/last`), so clients can't show "page X of Y".
- **W5 — Naive page ordering.** Pages sorted lexically (`getimage.py:61`), so
  `10.jpg` sorts before `2.jpg` unless zero-padded — reading order can be wrong.
- **W6 — Generic `application/octet-stream`** acquisition type rather than
  `application/x-cbz` / `application/x-cbr`; some clients use MIME to pick a reader.
- **W7 — Inconsistent XML escaping.** IDs/titles are escaped in Python via
  `xml.sax.saxutils.escape`, and hrefs contain literal `&amp;` inside f-strings
  (`opds.py:421` etc.) that then flow through Mako — fragile; double-escaping /
  under-escaping is easy to introduce.

---

## 6. Candidate requirements for foragerr's OPDS server (plain prose)

Baseline (match Mylar's useful behaviour):

- Serve an OPDS 1.2 Atom catalog from a single configurable base path, with a
  navigation root that links to browse-by-series, browse-by-publisher, recently
  added, reading lists, and story arcs, only surfacing shelves that have content.
- Provide acquisition feeds listing downloadable issues with per-entry title,
  author, summary, updated timestamp, and cover + thumbnail links.
- Support whole-file download of the original CBZ/CBR as an acquisition link, and
  serve it with a correct, specific MIME type (`application/vnd.comicbook+zip` /
  `+rar` or the `x-cbz`/`x-cbr` variants) rather than generic octet-stream.
- Offset/paged feeds with `next`/`previous`, and additionally advertise total
  result counts and `first`/`last` so iPad clients can show progress.

Modernisation / things Mylar gets wrong that we should fix:

- **Implement OPDS-PSE page streaming** (the `vaemendis.net/opds-pse` extension:
  `{pageNumber}`/`{maxWidth}` templated stream URL plus `pse:count`), since that is
  what page-flipping readers rely on for streaming rather than full download.
  Verify against Panels/Chunky current docs whether they prefer PSE streaming or
  whole-file download before committing to PSE as the primary path — the reference
  code does not establish this, and it should not be guessed. If PSE is included,
  compute `pse:count` lazily/cached, not by opening every archive on every feed
  render.
- **Natural (numeric) page ordering** inside archives, not lexical sort.
- **Actually implement search** if we advertise an OpenSearch descriptor — serve a
  valid `opensearchdescription+xml` document and a working search feed, or omit the
  search link entirely. (Mylar advertises but does not implement it.)
- **No path-traversal download endpoint.** Every download/stream must resolve the
  target from an internal identifier (issue id) to a path *inside* the managed
  library root, and reject anything that escapes it. Never serve a client-supplied
  filesystem path (the `deliverFile` anti-pattern).
- **Parameterise all SQL** — no string interpolation of client-supplied ids.
- **Authentication that is on by default and consistent with the main app.** Given
  the Tailscale deployment, rely on the tailnet as the primary boundary but still
  require app-level auth (e.g. a token/API key or Basic over the tailnet) rather
  than shipping an open endpoint; do not exempt OPDS from whatever auth the rest of
  the service uses. Require/assume TLS.
- **Correct, robust XML generation** (single escaping strategy, proper query-param
  encoding) — ideally via a library rather than hand-built f-strings.
- **Resource limits** on archive opening/image resizing (size caps, timeouts) to
  contain malformed-file / zip-bomb inputs on the untrusted parse path.
- Server-side cover/thumbnail generation from the archive as a fallback when no
  external cover URL exists (Mylar leaves many entries cover-less), served from a
  local cache.
- Consider offering OPDS 2.0 (JSON) alongside 1.2 for newer clients, but only if a
  target iPad reader benefits — flagged as optional/uncertain.
