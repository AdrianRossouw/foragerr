# Mylar3 DDL Downloader (GetComics provider) — Research Report

Source studied: `/Users/adrian/Projects/foragerr/.reference/mylar3/mylar/getcomics.py`
(1677 lines), queue/worker plumbing in `helpers.py` (`ddl_downloader`), integration in
`search.py`, `search_filer.py`, `webserve.py` (retry/requeue UI), mirror downloaders in
`mylar/downloaders/` (mega, mediafire, pixeldrain, external_server), and config in
`config.py` / `__init__.py`. Citations relative to
`/Users/adrian/Projects/foragerr/.reference/mylar3/mylar/`.

## 1. Behavioral catalogue

### 1.1 Provider identity & configuration

- Target site hardcoded: `GC_URL = 'https://getcomics.org'` (`__init__.py:219`).
- Feature gates: `ENABLE_DDL`, `ENABLE_GETCOMICS` (both default False), plus a second
  "DDL(External)" provider backed by a Mega-driven external server (`config.py:359-364`,
  `search.py:608-624`).
- Key knobs (`config.py:365-375`): `PACK_PRIORITY` (prefer multi-issue packs),
  `DDL_QUERY_DELAY` (default 15 s between search-page fetches), `DDL_LOCATION` (download
  dir), `DDL_AUTORESUME` (default True), `DDL_PREFER_UPSCALED` (default True),
  `DDL_PRIORITY_ORDER` (JSON list; default `["mega","mediafire","pixeldrain","main"]`,
  validated/reset at `config.py:1552-1571`), `ENABLE_FLARESOLVERR`+`FLARESOLVERR_URL`
  (Cloudflare solver), `ENABLE_PROXY`+`HTTP(S)_PROXY`.
- The provider object `GC` carries a spoofed Firefox 40 User-Agent and a
  `Referer: getcomics.org` header for all site traffic (`getcomics.py:131-134`); proxies are
  applied to the session when enabled (`getcomics.py:138-142`).

### 1.2 Cookie/session handling (Cloudflare)

`GC.cookie_receipt` (`getcomics.py:37-121`): cookies are persisted to
`<SECURE_DIR>/.gc_cookies.dat` (`getcomics.py:144`; SECURE_DIR defaults to
`<data_dir>/.secure`, `config.py:1212-1213`). If the file exists it is loaded into the
requests session; if not and FlareSolverr is enabled, Mylar POSTs
`{'url': GC_URL, 'cmd': 'request.get'}` to the FlareSolverr endpoint **with
`verify=False`** (`getcomics.py:57-63`) and stores the returned clearance cookies as JSON.
Without FlareSolverr, no cookies are stored (dead code path kept for the future,
`getcomics.py:77-102`). A corrupt cookie file is deleted and recreated
(`getcomics.py:111-114`).

### 1.3 Search

Entry: `search.py:943-958` builds `query = {'comicname', 'issue', 'year'}` and calls
`GC(query=..., provider_stat=...).search(is_info=...)`. RSS mode instead uses GetComics'
RSS feed via `rsscheck.ddl_dbsearch` with pack detection (`search.py:964-996`).

`GC.search` (`getcomics.py:162-304`):

- Query ladder `search_format = ['"%s #%s (%s)"', '%s #%s (%s)', '%s #%s', '%s %s']`
  (`getcomics.py:156`) — quoted exact, unquoted, no year, then name+year. When the wanted
  item is a TPB/no-issue-number (`is_info['chktpb']`), a bare comic-name query is prepended
  with punctuation and and/the stripped (`getcomics.py:168-187`); with `PACK_PRIORITY`, a
  pre-formatted `name year` query is prepended to surface packs first (`getcomics.py:175-178`).
- Each formatted query is fed to `perform_search_queries` (a generator) and the stream of
  parsed results is passed through `search_filer.search_check().check_for_first_result`,
  which applies Mylar's normal title/issue/year verification and returns the **first**
  acceptable match, preferring pack/non-pack per config (`getcomics.py:226-234`,
  `search_filer.py:1140-1155`). First verified match short-circuits the ladder.
- Between ladder steps it sleeps `DDL_QUERY_DELAY` (`getcomics.py:235-236`).
- Exception policy: timeouts → `'no results'`; connection refused → disable the whole DDL
  provider via `helpers.disable_provider` (`getcomics.py:243-257`); Cloudflare IUAM
  detection string also disables the provider (`getcomics.py:263-266`); any other exception
  is recorded with a full traceback via `helpers.log_that_exception`
  (`getcomics.py:268-295`).

`perform_search_queries` (`getcomics.py:327-374`): GET `https://getcomics.org/?s=<query>`,
following pagination via the "older posts" link until exhausted. Before each page fetch it
enforces a per-provider delay: `check_time(provider_stat['lastrun'])` vs `DDL_QUERY_DELAY`,
sleeping the remainder (`getcomics.py:331-337`; `search.py:4074-4078`). Each fetch updates
the `provider_searches` DB row (lastrun, hit count) (`getcomics.py:354-356`,
`search.py:4087-4123`). Non-200 responses abort with a "may be a CloudFlare block" warning
(`getcomics.py:348-350`). Results are deduped by URL (`seen_urls`) and "Weekly" roundup
posts are skipped unless the query itself is a Weekly (`getcomics.py:361-366`).

### 1.4 HTML scraping of search results

`parse_search_result` (`getcomics.py:376-509`), BeautifulSoup/html.parser over the search
page:

- Iterates `<article>` elements; extracts post id, first `<a href>` as the post link, and
  `<h1 class="post-title">` text (en-dash normalized) (`getcomics.py:394-400`).
- Pack detection (`check_for_pack`, `getcomics.py:1348-1624`): pulls a year or year-range,
  finds `#`-ranges or bare `N - M` numeric ranges, recognizes `vol/vol./volume` labels,
  TPB/GN/HC/One-Shot booktype markers, and "pack receipts" (`+ TPBs`, `+ Annuals`, ` & `,
  `getcomics.py:158`) to produce `{title, filename, series, year, pack, volume, annuals,
  gc_booktype, issues}`. Weekly-pack posts (`Marvel Week+`, `DC Week+` …) are dropped
  (`getcomics.py:412-420`).
- Year and size are scraped from the centered `<p style="text-align: center;">` info block;
  a fallback re-parses escaped HTML found inside `post-excerpt` (`getcomics.py:426-437`).
  Size strings are normalized (MB→M, GB→G, junk → `'0M'`/None) (`getcomics.py:446-473`).
- Post date from the `<time datetime>` attribute → pubdate string (`getcomics.py:475-483`).
- Returns `(resultlist, next_page_url)` where each result carries
  `site: 'DDL(GetComics)'` (`getcomics.py:478-509`).

### 1.5 Snatch: link resolution on the post page

When the searcher decides to snatch (`search.py:3124-3148`): `GC.loadsite(nzbid, link)`
downloads the post page to `<CACHE_DIR>/html_cache/getcomics-<id>.html`
(`getcomics.py:306-325`), then `parse_downloadresults(id, mainlink, comicinfo, pack_info)`
(`getcomics.py:511-1124`) parses the cached file:

- Walks all centered `<p>` blocks ("beeswax"): header blocks give series/year/size; a series
  label containing `HD-Upscaled` / `SD-Digital` / `HD-Digital` opens a quality-keyed section
  (`getcomics.py:583-598`); `<div class="aio-pulse">` blocks contain download anchors whose
  `title` attribute names the host ("Download Now", "Mirror Download", "Mega", "MediaFire",
  "Pixeldrain", "Read Online") (`getcomics.py:630-667`). "Read Online" links are skipped;
  `sh.st` (paywall/shortener) hrefs are rejected outright (`getcomics.py:657`,
  also re-checked at `getcomics.py:893-895` and at download time `getcomics.py:1128-1132`).
- Previously failed link types for this item (`link_type_failure`) are filtered out so a
  retry tries a different host (`getcomics.py:643-654`).
- **Mirror/link-type preference**: candidate links are keyed
  `<quality>:<host>` (e.g. `HD-Upscaled:mega`, `normal:download now`). Selection walks
  `DDL_PRIORITY_ORDER`; with `DDL_PREFER_UPSCALED` it first tries HD-Upscaled, then
  HD-Digital, per host, then SD/normal fallbacks (`getcomics.py:734-899`). One link wins.
- Multi-part pack pages: if the page instead lists `<ul><li>` entries pointing to
  `run.php`/`go.php`/`comicfiles.ru`/`links.php` "Main Server" links, each part's
  series/issues/year/size is parsed from the `Series #a-b (year) (size)` label, filtered by
  `pack_check` (parts must fall in the wanted issue range, `getcomics.py:1626-1640`), and
  each part is queued separately (`getcomics.py:916-981`, queue split at
  `getcomics.py:1044-1054` with ids `id-1`, `id-2`, …). A TPB-section variant exists but is
  dead code due to a `bookype` typo (`getcomics.py:989` — NameError swallowed upstream).
- Each queued item is upserted into the `ddl_info` table (status `Queued`, series, size,
  link, link_type, ids) and pushed onto the in-memory `mylar.DDL_QUEUE`
  (`getcomics.py:1078-1122`). Link types: `GC-Main`, `GC-Mirror`, `GC-Mega`, `GC-Media`,
  `GC-Pixel` (`getcomics.py:1056-1069`). Returns `{'success': True, 'site': link_type}` and
  the searcher reports "snatched, queued in position N" (`search.py:3140-3148`).

### 1.6 Queue execution (worker thread)

`helpers.ddl_downloader(queue)` (`helpers.py:3293-3446`) is a dedicated daemon thread
(started at `__init__.py:756-757`; shutdown via an `'exit'` sentinel, `__init__.py:784`):

- Single-flight: `mylar.DDL_LOCK` global plus 5 s polling; only one DDL download at a time
  (`helpers.py:3297-3300`, `getcomics.py:1134-1141`).
- Marks `ddl_info` row `Downloading`, then dispatches by link type: GC-Main/Mirror →
  `GC.downloadit`; GC-Mega → `mega.MegaNZ.ddl_download`; GC-Media → `mediafire.MediaFire`;
  GC-Pixel → `pixeldrain.PixelDrain` (`helpers.py:3325-3345`). Note a comparison typo
  `'GC_Mirror'` vs the stored `'GC-Mirror'` (`helpers.py:3334`) — mirror links fall through
  to no handler (`ddzstat` then references a stale/undefined value).
- `GC.downloadit` (`getcomics.py:1126-1310`): re-loads cookies, optional `Range` header for
  resume (`getcomics.py:1149-1153`), streams the link with 30 s connect/read timeouts.
  The **filename is derived from the final redirected URL**:
  `os.path.basename(urllib.parse.unquote(t.url))`, stripping "GetComics.INFO" and embedding
  the issue id as `name[__<issueid>__].ext` (`getcomics.py:1163-1171`). If Content-Length is
  missing it rewrites `run.php-url=`/`go.php-url=` → `run.php-urls` and retries once;
  still missing → treat as click-bait/ad page and fail the attempt
  (`getcomics.py:1175-1235`). Filename and remote size are recorded in `ddl_info`
  (`getcomics.py:1238-1242`). The file streams 1 KiB chunks into
  `DDL_LOCATION/<filename>` (append mode when resuming; pre-existing file is deleted or
  renamed `.1` on collision) (`getcomics.py:1261-1289`).
- Zip handling: a downloaded `.zip` (typically a pack) is extracted with
  `zipfile.extractall` into a folder named after the zip, then the zip is deleted
  (`getcomics.py:1313-1346`).

### 1.7 Verification, post-processing, failure handling

- **File-condition check**: after any single-file success, `check_file_condition` validates
  magic numbers and runs full CRC tests for ZIP/RAR (and PDF checks) (`helpers.py:3353-3358`,
  `helpers.py:5008-5048`); failure flips the result to failed with the link type recorded.
- Success → `ddl_info` status `Completed`; if post-processing is enabled the item is pushed
  to `mylar.PP_QUEUE` with `ddl: True` and `download_info={'provider':'DDL','id':...}`
  (`helpers.py:3360-3387`), which feeds `process.Process(...).post_process()`
  (`helpers.py:3459-3490`). Pack completions clear their member issue IDs from
  `PACK_ISSUEIDS_DONT_QUEUE` (a map that stops the search queue re-searching issues already
  covered by an in-flight pack, `helpers.py:3398-3408`, `helpers.py:3506-3509`); the cached
  post HTML is deleted (`ddl_cleanup`, `helpers.py:3448-3456`).
- Failure → the failed `link_type` is appended to a per-item `link_type_failure` list and
  `parse_downloadresults` is re-invoked against the cached page to pick the next host
  (`helpers.py:3419-3431`). When every host has been tried, status becomes `Failed`, the
  snatch is reversed (`reverse_the_pack_snatch`, restoring issue statuses,
  `helpers.py:3432-3440`, `helpers.py:2674`), and the cache is cleaned.
- Manual queue management from the UI: retry/resume/abort/remove/restart_queue re-inject
  `ddl_info` rows into `DDL_QUEUE`; resume uses the on-disk partial file size as the Range
  offset when `DDL_AUTORESUME` is on (`webserve.py:3735-3790`).

### 1.8 Politeness summary

- Search-page fetches: ≥ `DDL_QUERY_DELAY` (15 s default) apart, tracked per provider in
  the DB, and an extra sleep between query-ladder steps. Post-page loads and the actual
  file download are deliberately not delayed (comment at `getcomics.py:332`).
- Downloads: strictly serialized (one at a time) via `DDL_LOCK`.
- Fixed spoofed browser User-Agents everywhere (`getcomics.py:132`,
  `downloaders/pixeldrain.py:31-34`, `downloaders/mediafire.py:33`); Referer pinned to the
  site. Cloudflare evasion via persisted clearance cookies / FlareSolverr.
- Provider self-disables on connection-refused and Cloudflare-IUAM failures.

## 2. End-to-end sequence: one issue via GetComics

1. Search queue pops a wanted issue → `search.searchforissue` → provider loop reaches
   `DDL(GetComics)` (`search.py:270-275,608-615`).
2. `GC.search` loads cookies, walks the query ladder; for each query,
   `perform_search_queries` fetches `getcomics.org/?s=...` pages (rate-limited, deduped),
   `parse_search_result` scrapes articles into result dicts, and
   `search_filer.check_for_first_result` verifies title/issue/year/booktype and returns the
   first match (pack-preference aware).
3. Searcher snatches: `GC.loadsite` caches the post HTML; `parse_downloadresults` scrapes
   quality sections and host links, applies `DDL_PRIORITY_ORDER` + `DDL_PREFER_UPSCALED`,
   upserts `ddl_info` (Queued) and puts item(s) on `DDL_QUEUE`; issue is marked Snatched.
4. `ddl_downloader` worker picks it up (single-flight), marks Downloading, and runs the
   host-specific downloader (GC main server streaming, or Mega/MediaFire/PixelDrain
   modules).
5. On completion: filename recorded, zip packs extracted, magic-number + CRC verification;
   success → status Completed → `PP_QUEUE` → post-processor imports/renames into the
   library; failure → next host retried via `link_type_failure`, else status Failed and the
   snatch reversed. Cached HTML removed on terminal states.

## 3. Weaknesses worth fixing

1. **Two-phase scraping with cached HTML as source of truth**: search scrape and
   link-resolution scrape are separate, and retries re-parse a cached copy that can go
   stale; the whole flow is coupled to GetComics' exact DOM (centered `<p>`, `aio-pulse`
   divs, anchor `title` text). Any site redesign silently breaks matching. Foragerr should
   isolate parsing behind a versioned adapter with fixture-based tests.
2. **State smeared across globals, DB, and in-memory queue**: `DDL_LOCK`, `DDL_QUEUED`,
   `PACK_ISSUEIDS_DONT_QUEUE` globals + `ddl_info` table + `queue.Queue` must be kept in
   sync manually; restart loses queue order (UI restore exists but is manual).
3. **Observed defects**: `'GC_Mirror'` vs `'GC-Mirror'` typo means mirror-link downloads hit
   no dispatcher (`helpers.py:3334`); `bookype` NameError kills the TPB extras branch
   (`getcomics.py:989`); `possible_more` can be referenced before assignment
   (`getcomics.py:916`); `issue_list` computes and logs but returns nothing
   (`getcomics.py:1642-1669`); giant copy-pasted host-preference ladder
   (`getcomics.py:744-899`) begs for a table-driven rewrite.
4. **Weak size/verification model**: remote size is only used for display/resume; there is
   no expected-size or hash check against the search result; verification is generic
   archive CRC only. Click-bait detection is "no Content-Length" heuristics.
5. **Resume trust**: resume offset comes from the local partial file size with no validation
   that the server honored the Range request (a 200-with-full-body response would corrupt
   the file by appending).
6. **1 KiB streaming chunks** are needlessly slow for multi-hundred-MB packs.
7. **Politeness gaps**: no jitter, no per-host backoff on 429/503, no cap on pagination
   depth (a broad query walks every result page of the site at 15 s intervals).

## 4. Security-relevant observations (for STRIDE / risk register)

- **Untrusted HTML → filesystem paths**: the download filename is derived from the final
  URL after following arbitrary redirects from scraped links
  (`getcomics.py:1163-1171`). `unquote` happens **before** `os.path.basename`, and the name
  is then joined into `DDL_LOCATION`. basename mostly defuses traversal, but the name is
  fully attacker-controlled (weird/hostile names, `..` edge cases, device names on other
  platforms). Foragerr must sanitize/generate its own filenames. (Tampering/path traversal)
- **Arbitrary redirect following with session cookies**: scraped hrefs are fetched with the
  provider session (cookies attached) and redirects followed blindly — an injected link can
  exfiltrate the Cloudflare session or point at internal addresses (**SSRF**: nothing
  restricts scheme/host of scraped links; `run.php`/`go.php` rewrites even mutate them,
  `getcomics.py:1180-1182`). Foragerr should allowlist schemes/hosts per provider and cap
  redirect chains. (SSRF / info disclosure)
- **Zip extraction of hostile archives**: `zipfile.extractall` on downloaded packs
  (`getcomics.py:1324-1326`) — zip-bombs are unmitigated (no size/entry caps) and symlink
  tricks are not filtered; extraction happens before any verification. (DoS/tampering)
- **FlareSolverr call uses `verify=False`** (`getcomics.py:60`) and the FlareSolverr URL is
  effectively an internal SSRF pivot; clearance **cookies are persisted in plaintext** at
  `.secure/.gc_cookies.dat` (`getcomics.py:68-69,144`). (MITM / credential-adjacent storage)
- **Scraped text flows into logs, DB, and UI unescaped** (series titles, sizes, years from
  the page) — treat as untrusted output everywhere (XSS in web UI; log injection).
- **Cloudflare evasion + spoofed UA + shortener filtering (`sh.st`)** are ToS-sensitive
  behaviors to consciously decide on, and the hardcoded single upstream (`getcomics.org`)
  means a domain takeover instantly becomes a malware-delivery channel — the CRC check does
  not authenticate content. Consider content-type checks and CBZ/CBR structural validation
  before anything touches the library. (Spoofing/repudiation)
- **Proxy settings apply only to this provider's session** (`getcomics.py:138-142`) — split
  tunneling surprise: other traffic (CV, indexers) ignores the proxy.

## 5. Candidate requirements (plain prose)

- The system shall implement a GetComics DDL provider that searches via the site's query URL
  using an escalating series of query forms (exact quoted, name+issue+year, name+issue,
  name+year) and stops at the first result that passes the standard match verification.
- The provider shall parse search and post pages defensively behind a dedicated adapter,
  with recorded HTML fixtures and tests, and shall fail gracefully (log + skip) when the
  page structure is unrecognized.
- The provider shall rate-limit page fetches with a configurable minimum interval and
  jitter, persist last-run/hit statistics, and back off or self-disable on Cloudflare
  blocks, connection failures, and HTTP 429/503.
- The provider shall recognize single issues, issue packs (ranges, annuals, volume packs),
  and TPB/GN/HC book types from post titles, and shall suppress duplicate searches for
  issues already covered by an in-flight pack download.
- The provider shall enumerate all offered download hosts and quality tiers for a post and
  select among them according to a user-configurable priority order and quality preference,
  rejecting known paywall/shortener links.
- Downloads shall run one at a time from a persistent queue whose items survive restart,
  with statuses (queued, downloading, completed, failed) visible and manually controllable
  (retry, resume, abort, remove).
- On download failure, the system shall retry the same release via the next untried host
  and, only when all hosts are exhausted, mark the item failed and restore the issue's
  previous wanted state.
- The system shall generate its own safe filenames rather than trusting names derived from
  redirect URLs, shall restrict fetched URLs to allowed schemes/hosts, and shall cap
  redirect chains.
- Downloaded archives shall be validated (magic number, archive integrity, size and entry
  caps during extraction) before post-processing, and hostile archive contents (traversal,
  symlinks, bombs) shall be rejected.
- Completed downloads shall flow automatically into the standard post-processing/import
  pipeline with provenance (provider, source link, queue id) recorded.
- Session state used for Cloudflare clearance shall be stored with restricted permissions
  and treated as a credential; any solver service integration shall verify TLS.
