# Mylar3 ComicVine Integration — Research Report

Source studied: `/Users/adrian/Projects/foragerr/.reference/mylar3/mylar/cv.py` (1506 lines),
`mylar/mb.py` (search + arc lookup, 657 lines), plus callers in `importer.py`, `updater.py`,
`librarysync.py`, `helpers.py`, `getimage.py`, `webserve.py`, and configuration in
`config.py` / `__init__.py`. All file:line citations below are relative to
`/Users/adrian/Projects/foragerr/.reference/mylar3/mylar/`.

## 1. Behavioral catalogue

### 1.1 Endpoints and query patterns

Base URL is hardcoded: `CVURL = 'https://comicvine.gamespot.com/api/'` (`__init__.py:358`).
All request URLs are built by string concatenation in two dispatchers:

- `cv.pulldetails(comicid, rtype, ...)` (`cv.py:26-108`) — one function, one URL template per
  `rtype`:
  - `comic` → `volume/4050-<id>/` with `field_list=name,count_of_issues,issues,start_year,site_detail_url,image,publisher,description,first_issue,deck,aliases` (`cv.py:36-38`). The `4050-` volume prefix is prepended if missing (`cv.py:37`).
  - `issue` → `issues/?filter=volume:<id>` (or `filter=id:<pipe-separated issueids>` for story arcs) with a narrow `field_list` (`cv.py:39-49`); paginated by `offset`.
  - `image` / `firstissue` / `imprints_first` → `issues/?filter=id:<issueid>&field_list=cover_date,store_date,image` or `volume/<id>/?field_list=image` (`cv.py:50-55`).
  - `storyarc` → `story_arcs/?filter=name:<name>&field_list=cover_date` (`cv.py:56-57`).
  - `comicyears` → `volumes/?filter=id:<id|id|...>` batched lookup for arc member series (`cv.py:58-59`).
  - `import` → `issues/?filter=id:<idlist>` used by library import when issue IDs are known from metadata tags (`cv.py:60-61`).
  - `single_issue` → `issue/4000-<issueid>` in **JSON** format (`cv.py:62-64`).
  - `db_updater` → `issues/?filter=date_last_updated:<start>|<end>&sort=date_last_updated:asc` in JSON (`cv.py:65-66`) — the incremental "what changed on CV since last run" poll.
- `mb.pullsearch(comicapi, comicquery, offset, search_type)` (`mb.py:56-99`) — series search.
  Notably it does **not** use CV's `search` resource; it uses the `volumes` (or `story_arcs`)
  list endpoint with a chained name filter: `filter=name:word1,name:word2,...`
  (`mb.py:59-66`), sorted `date_last_updated:desc`. Each whitespace-delimited word of the
  query becomes its own `name:` filter (AND semantics on CV's side).

Most responses are requested as XML and parsed with `xml.dom.minidom.parseString`
(`cv.py:92`); `single_issue` and `db_updater` use JSON (`cv.py:88-89`). ID conventions: CV
type prefixes `4050-` (volume), `4000-` (issue), `4045-` (story arc) appear throughout
(`cv.py:37,64`, `mb.py:527`).

### 1.2 API key handling

- Single user-supplied key `COMICVINE_API` (config default None, `config.py:154`). Every
  request refuses to run without it (`cv.py:30-32`, `mb.py:141-143`) — Mylar deliberately has
  no bundled key.
- The key is embedded directly in the URL query string (`cv.py:38` et al.), so it would appear
  in any URL logging (the `logger.info('CV.PULLURL...')` lines are commented out —
  `cv.py:67`, `mb.py:69`) and in proxy logs. **Security-relevant: key-in-URL is easy to leak;
  Foragerr should send it as a parameter via a requests `params` dict and scrub it from logs.**
- Config load strips a literal `'None'` prefix from corrupted keys (`config.py:1314-1322`).

### 1.3 Rate limiting / backoff / ban handling

- Politeness is a fixed **pre-request sleep**, not a token bucket: before *every* CV call,
  sleep `CVAPI_RATE` seconds (default 2, floor of 2 enforced) (`cv.py:69-72`, `mb.py:72-75`,
  `mb.py:531-534`; default at `config.py:153`).
- Ban detection: if the XML parse fails and the body contains `<title>Abnormal Traffic
  Detected`, Mylar logs that CV has banned the server IP for exceeding the API rate limit
  (`cv.py:93-95`, `mb.py:88-90`). No automatic cool-down or retry-after handling — it just
  returns None.
- A global health flag `mylar.BACKENDSTATUS_CV` is flipped `'up'`/`'down'` on
  success/failure (`cv.py:79-84,98,105`) and surfaced in the UI.
- The only retry logic is in `GetComicInfo`: if `site_detail_url` is missing (assumed CV
  timeout), sleep 10s and recurse with `safechk+1`, aborting after 5 tries
  (`cv.py:297-303,400-407`). Note the recursion's return value is discarded (see §3).
- `db_updater` self-throttles a large backlog: >1500 changed issues → process 1500 now,
  stagger the rest to later runs (`cv.py:266-271,290-291`).

### 1.4 Pagination

CV pages are 100 results. Both `getComic('issue')` and `findComic` first fetch page 0, read
`number_of_total_results`, then loop `countResults += 100` re-querying with
`offset=countResults` (`cv.py:137-159`, `mb.py:154-167`). Search results are capped at 1000
with a warning (`mb.py:158-160`). Batched ID lookups (`import`) are chunked 100 IDs per call
joined by `|` (`cv.py:189-214`). Mid-pagination CV failure returns partial results rather than
failing the operation (`cv.py:150-153`).

### 1.5 Series/volume/issue mapping

- `GetComicInfo` (`cv.py:297-528`) maps a CV volume to Mylar's series record: name, publisher
  (default `'Unknown'`), first-issue id, start year (with trailing `-`/`?` sanitization,
  `cv.py:365-366`), site URL, aliases (newline → `##` delimiter, `cv.py:410-417`), cover image
  URLs with fallbacks, and issue count. If CV's `count_of_issues` disagrees with the number of
  issue elements returned, the actual element count wins (`cv.py:311-322`).
- **Volume number, book type, and imprint are not API fields — they are mined from the
  free-text `description` and `deck` HTML** via `get_imprint_volume_and_booktype`
  (`cv.py:1124-1425`):
  - Booktype classification (Print / Digital / TPB / GN / HC / One-Shot) is keyword matching
    over the first 30-60 chars of deck/description with a long list of negative phrases
    ("also available as a print", "reprints", "can be found", ...) (`cv.py:1280-1328`).
    A "FAKE NEWS" guard rejects one-shot mentions preceded by words like "preceding" or
    "continued from" (`cv.py:1308-1326`).
  - Volume extraction searches for "volume N" and "Nth volume" forms, converting written
    ordinals/roman numerals via `basenum_mapping` (`cv.py:1344-1421,1427-1481`), first in the
    description, then the deck; "New 52" is stripped first (`cv.py:1337`). A "one-shot
    collected ... volume" pattern flags the found volume as `incorrect_volume` instead of
    accepting it (`cv.py:1353-1362,1402-1404`).
  - Imprint resolution walks a bundled `PUBLISHER_IMPRINTS` mapping with publication-year
    ranges, sometimes issuing an extra CV call (`imprints_first`) to get the first issue's
    cover/store month to disambiguate boundary years (`cv.py:1137-1250`).
  - One-shot forcing: exactly 1 issue + series year in the past + not already a
    TPB/HC/GN → treat as One-Shot (`cv.py:991-994`).
- TPB contents: when a description starts "trade paperback ... collecting", the embedded
  `<a data-ref-id>` links are scraped with BeautifulSoup to build an `Issue_List` of the
  collected series/issue ranges, skipping "Next/Previous volume" bullet lists (`cv.py:420-496`).
- `GetIssuesInfo` (`cv.py:530-662`) maps each issue element to
  Comic_ID/Issue_ID/Issue_Number/CoverDate/StoreDate/Issue_Name/images, defaulting missing
  dates to `0000-00-00`; a "digital date" is heuristically extracted from the trailing 90
  chars of the issue description when it mentions both "digital" and "print"
  (`cv.py:599-611`). Issues without an issue number are skipped as unsupported (`cv.py:612-615`);
  a leading `Issue #` prefix is stripped (`cv.py:618-619`). It also tracks the earliest cover
  date (`firstdate`) for series-year correction.
- `GetSeriesYears` (`cv.py:705-1004`) does the equivalent volume-level mapping for every
  series inside a story arc; `GetImportList` (`cv.py:1034-1083`) maps issue-ID batches back to
  (ComicID, IssueID, ComicName, Issue_Number) for the library importer.
- `singleIssue` (`cv.py:1006-1032`) maps the JSON single-issue response including person
  credits.

### 1.6 Search + volume-matching heuristics (mb.findComic)

`findComic(name, mode, issue, limityear, search_type)` (`mb.py:101-512`):

- Query normalization: strips common words `and/the/&/-` with positional checks
  (`mb.py:109-122`), tokenizes remaining words with `\w+` (`mb.py:128-129`), and encodes `+`
  as `%2B` via a `PLUS` sentinel round-trip (`mb.py:125-135`).
- For each result volume, plausibility filters:
  - **Issue-count sanity**: computes `cnt_numerical = count_of_issues + ceil(first_issue_number)`
    and requires it ≥ the wanted issue number minus 1 — i.e., "does this volume plausibly
    contain issue N?" (`mb.py:267-310`). First issue `½` is treated as 1 (`mb.py:284-285`).
  - **Year-range filter**: builds `yearRange = start_year .. start_year + count/12` (approx.
    one year per 12 issues) and requires the caller's `limityear` to intersect it
    (`mb.py:348-366`).
  - **Publisher ignore list** via `ignored_publisher_check` (`mb.py:391-393`).
  - Description/deck are run through `cv.get_imprint_volume_and_booktype` so search results
    already carry volume/booktype/imprint (`mb.py:407-429`).
  - Results are annotated `haveit` when the ComicID is already in the library (`mb.py:481-484`).
- Story-arc search: for each arc hit, `storyarcinfo(xmlid)` re-queries
  `story_arc/4045-<id>` to enumerate member issue IDs into a `id,order|id,order|...`
  `arclist` string and to derive the arc year from the first-appearance issue
  (`mb.py:514-656`).
- The final choice among candidate volumes is made upstream (importer/searcher UIs); the
  matching heuristics above only prune.

### 1.7 Caching

- **No HTTP or response caching at all** for CV API data — every operation re-fetches. The
  only persistence is Mylar's own SQLite tables written by the importer/updater.
- Cover images are downloaded separately and cached to the cache dir (`getimage.py:225`
  fetches image URLs via `cv.getComic(..., 'image')`).
- The `db_updater` flow is the incremental-sync mechanism: `updater.py:2085` calls
  `getComic(rtype='db_updater', dateinfo=<last-run UTC timestamp>)`; results are sorted by
  `date_last_updated` and turned into per-issue/per-volume refresh work (`cv.py:220-295,
  1085-1111`). Timezone care: Mylar stores UTC, CV returns US/Pacific, so the window is
  converted with `pytz` (`cv.py:238-247`). Configurable `PROBLEM_DATES` windows (periods when
  CV data was known-bad) are excised from the query range (`cv.py:227-236`).
- `check_that_biatch` (`cv.py:1483-1506`) is a data-integrity guard on refresh: if >2 of
  {name, year, publisher, detail URL} changed, assume CV deleted/reused the volume ID and
  pause the series instead of clobbering local data.

### 1.8 Error handling

- Transport errors: caught broadly; log a warning, set `BACKENDSTATUS_CV = 'down'`, return
  None (or False for `db_updater`) (`cv.py:74-82`).
- Parse errors: `ExpatError` distinguishes the ban page from generic CV flakiness
  (`cv.py:93-99`); other exceptions log `r.content` (`cv.py:100-106`).
- Field extraction is wall-to-wall bare `try/except` with string defaults `'None'`/`'0000'`/
  `'Unknown'` — missing data degrades silently rather than failing (throughout
  `GetComicInfo`/`GetIssuesInfo`/`GetSeriesYears`).
- Callers get `None`/`False`/partial lists and mostly log-and-continue.

### 1.9 TLS & headers

- `CV_VERIFY` config (default True) can disable certificate verification for every CV call
  (`cv.py:75`, `mb.py:81`, `config.py:156`). **Security-relevant: a config flag that turns
  off TLS verification for the metadata source.**
- Requests carry a spoofed browser User-Agent (`CV_USER_AGENT`, default a Chrome 122 UA
  string, `config.py:160`; header assembled at `__init__.py:342`). Old UA values are migrated
  forward and synced into ComicTagger's settings (`config.py:1483-1528`).

## 2. End-to-end sequence: adding a series

1. User searches → `mb.findComic` tokenizes the name, calls `pullsearch`
   (`volumes?filter=name:...`), paginates to ≤1000 results, applies issue-count/year/publisher
   filters, mines volume/booktype/imprint from description HTML, returns candidate list
   (`mb.py:101-512`).
2. User picks a volume → `importer.addComic...` calls `cv.getComic(comicid, 'comic',
   series=True)` (`importer.py:192`), which does `pulldetails('comic')` → `GetComicInfo`
   parse (name/publisher/year/images/volume/booktype/imprint/TPB contents).
3. If start year is missing, `cv.getComic(comicid, 'firstissue', FirstIssueID)` fetches the
   first issue's cover date (`importer.py:265`).
4. `cv.getComic(comicid, 'issue')` pages through `issues?filter=volume:<id>` 100 at a time,
   building the issue table via `GetIssuesInfo` and the earliest cover date
   (`importer.py:278`, `cv.py:111-163`).
5. Importer writes series+issues to SQLite, fetches cover art (`getimage.py`), and marks
   wanted issues.
6. Ongoing: the scheduled updater periodically calls `getComic('db_updater', dateinfo=
   <last check>)` to fetch CV-side changes sorted by update time and refreshes affected
   series/issues (`updater.py:2085`, `cv.py:220-295`), with `check_that_biatch` guarding
   against CV volume-ID reuse/wipes. Each request in every step is preceded by the 2-second
   sleep.

## 3. Weaknesses worth fixing (observed defects included)

1. **Fixed sleep instead of rate limiting**: 2s unconditional sleep before every call wastes
   time when idle and still doesn't guarantee compliance under concurrency (no lock around
   `cv.pulldetails`; `mb_lock` exists at `mb.py:40` but is never acquired — the `with
   mb_lock` is commented out at `mb.py:103`). No 420/429 or Retry-After handling; ban is
   detected only after the fact by scraping the ban page title.
2. **Broken retry**: `GetComicInfo`'s timeout retry recurses but discards the result and falls
   through with a partially-built dict (`cv.py:404-407` — no `return`).
3. **Dead/buggy code paths**: `dom.getElementByTagName` typo (`cv.py:508`) makes the
   `original_url` image fallback unreachable; `mb.storyarcinfo` references undefined `result`
   (should be `arcdom`) at `mb.py:608-618` so image/thumb always fall back via exception;
   the ExpatError handler logs undefined `e` (`mb.py:551`); `getcomics`-style `bookype` typo
   equivalents exist here too. Bare excepts hide all of this.
4. **XML minidom + index-coupled parsing**: fields are located by scanning flat
   `getElementsByTagName` lists and checking `parentNode.nodeName` with parallel-index
   assumptions (e.g. `mb.py:282-283` reads `issue_number[i]` based on `name[i]`'s parent) —
   fragile to any response-shape change. JSON (which CV supports everywhere) would eliminate
   this entire class.
5. **Volume/booktype from prose**: critical library semantics (volume number, print/TPB/HC,
   imprint, TPB contents) are regex/keyword heuristics over marketing copy; they misfire and
   have accreted negative-phrase lists. Foragerr should treat these as best-effort hints with
   user override, and persist the provenance.
6. **No caching / no ETag / no conditional requests**: every refresh re-downloads everything;
   the only incremental path is the separate db_updater poll.
7. **Silent degradation**: pervasive `except: field = 'None'` means bad data enters the DB
   with sentinel strings (`'None'`, `'0000'`, `'0000-00-00'`) that all downstream code must
   special-case.
8. **String-sentinel API**: functions return `None`, `False`, `'no results'`, dicts, or lists
   depending on path; `'None'` string vs `None` confusion is endemic (`cv.py:30`,
   `config.py:1314-1322`).

## 4. Security-relevant observations (for STRIDE / risk register)

- **API key in URL query string** for every request (`cv.py:38` etc.); leaks via logs,
  proxies, referer-style exposure. Mitigate: params dict + log scrubbing. (Info disclosure)
- **`CV_VERIFY` disables TLS verification globally** for CV traffic (`config.py:156`,
  `cv.py:75`). If Foragerr keeps a knob at all it must be per-host, defaulted on, and flagged
  in security docs. (Tampering/MITM)
- **Untrusted HTML parsed from CV descriptions** with BeautifulSoup (`cv.py:376-377,
  426-435`, `mb.py:407`): attacker-influenced wiki content (ComicVine is user-editable!)
  flows into series names, aliases, issue lists, and is later rendered in Mylar's web UI.
  Parsing itself is safe-ish (html.parser), but the derived strings must be treated as
  untrusted output (XSS in UI, and they influence search/download queries downstream —
  a wiki edit can steer what Foragerr searches for on DDL/Usenet). (Injection/steering)
- **Spoofed browser User-Agent** (`config.py:160`) — a ToS/politeness decision to make
  consciously rather than inherit.
- **No response size/time bounds**: `requests.get` without timeout in `cv.pulldetails`
  (`cv.py:75` has no `timeout=`) — a hung CV connection blocks the calling scheduler thread
  indefinitely. (DoS)
- **XML parsing of remote content** via minidom/expat — expat is not entity-expansion safe in
  all configurations; prefer JSON responses. (DoS)

## 5. Candidate requirements (plain prose)

- The system shall use a user-supplied ComicVine API key, sent outside the logged URL, and
  shall never write the key to logs, files, or error messages.
- The system shall enforce a client-side ComicVine rate limit (configurable, default no more
  than one request per 2 seconds) shared across all concurrent operations, and shall back off
  and surface a clear status when ComicVine signals rate-limit bans or errors.
- The system shall request JSON responses with explicit field lists, and shall bound every
  request with connect/read timeouts and TLS verification enabled.
- The system shall page through ComicVine results (100 per page) and shall tolerate partial
  pagination failure by persisting what was retrieved and scheduling a retry.
- The system shall map ComicVine volumes to series records (name, publisher, imprint, start
  year, issue count, description, cover art) and issues to issue records (number, name,
  cover/store dates, images), storing sentinel-free typed values (nullable fields, not the
  string "None").
- The system shall derive book type and volume number heuristically from description/deck
  text, shall record that these values are heuristic, and shall let the user override them
  without the override being clobbered by refresh.
- Series search shall filter candidates by plausible issue count and publication-year range
  and shall exclude user-ignored publishers.
- The system shall support incremental metadata sync by querying issues/volumes changed since
  the last successful sync, correctly converting between UTC and ComicVine's US/Pacific
  timestamps.
- On refresh, the system shall detect wholesale identity changes of a ComicVine volume
  (name/year/publisher/URL majority mismatch) and pause the series for manual review instead
  of overwriting local data.
- All strings originating from ComicVine (names, aliases, descriptions) shall be treated as
  untrusted: HTML-stripped on ingest, encoded on output, and never interpolated into shell,
  SQL, or filesystem paths without sanitization.
