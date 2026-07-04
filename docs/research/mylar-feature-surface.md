# Mylar3 Full Feature Surface — Research Report

**Scope**: complete inventory of Mylar3 capabilities from `.reference/mylar3`, EXCLUDING deep
coverage of four areas owned by other agents — filename parsing (`filechecker.py`), ComicVine
client (`cv.py`), DDL/GetComics (`getcomics.py`), OPDS (`opds.py`). Those appear as one-liners
in the capability map only.

**Method**: six parallel read-only code surveys (weekly pull + arcs; search scheduling;
post-processing; torrents/download clients; config + notifiers; core/API/DB/jobs). All file
paths below are relative to `/Users/adrian/Projects/foragerr/.reference/mylar3/` unless
absolute. No repo files were touched.

**Scale reference**: ~56k lines in `mylar/` (webserve.py 9.7k, helpers.py 5k, search.py 4.3k,
PostProcessor.py 3.6k, config.py 2.1k).

---

## 1. Weekly pull list

**Source of data**: three pull methods selected by `ALT_PULL`, but config force-pins it to `2`
(`config.py:1157-1159`), so the only live source is the **"walksoftly" JSON API**
(`https://walksoftly.itsaninja.party/newcomics.php?week=&year=`, `locg.py:51-57`) — a League of
Comic Geeks-derived third-party aggregation. Legacy paths (PreviewsWorld scrape in `newpull.py`,
flat `newreleases.txt` file) are dead code. Each run queries **both previous and current week**
to catch stragglers (`weeklypull.py:76-99`). Error codes handled: 619 bad date, 522 backend
down, 666 client-update-required (`locg.py:63-73`); failure just leaves stale data — no
fallback source.

**Storage**: `weekly` table `(SHIPDATE, PUBLISHER, ISSUE, COMIC, STATUS, ComicID, IssueID,
DynamicName, weeknumber, year, volume, seriesyear, annuallink, format, ...)` (`__init__.py:810`).
The week's rows are deleted then re-upserted per refresh (`locg.py:115-147`), default
`STATUS='Skipped'`. Companion tables: `upcoming` (this week's wanted), `futureupcoming`
(solicited future issues incl. new #1s).

**Matching to watched series** (`new_pullcheck()`, `weeklypull.py:890-1366`): builds a
watchlist of Active + "continuing" series (recency-checked per publisher, ~45 days), loads
alternate search names and annual release IDs, then joins `weekly` against `comics`/`annuals`
with three match types: (a) **idmatch** on CV ComicID (walksoftly supplies IDs), with booktype
guard; (b) **annualidmatch** via annual ReleaseComicIDs / `annuallink` (gated on `ANNUALS_ON`);
(c) **namematch** on normalized DynamicName, accepted only if issue number is a sane
next-in-sequence (0 ≤ delta < 3) (`weeklypull.py:1024-1099`). A date-range safety check in
`updater.upcoming_update()` (issue date must be within pull week ±2 days) reverts bad matches
(`updater.py:583-614`). If a pull issue isn't yet in the local issue table, a **forced series
refresh is queued** (`weeklypull.py:1268-1307`).

**Cadence & auto-want**: scheduler job "Weekly Pullist" runs **every 4 hours (fixed)**
(`__init__.py:508-509`); manual `pullrecreate`/`manualpull` from UI (`webserve.py:3131-3139`);
re-poll throttled to ~2h unless forced (`updater.py:701`). `AUTOWANT_UPCOMING` flips matched
new issues to `Wanted` (`weeklypull.py:1257-1261`, `updater.py:721-734`); search is NOT
triggered by the pull — Wanted issues wait for the shared Auto-Search job. Weekly statuses:
Skipped / Wanted / Snatched / Downloaded / Archived / Mismatched / Incomplete / Paused.

**Extras**: `future_check()` watches `futureupcoming` for #1/#0 issues and **auto-adds the
series** via CV search + fuzzy match (`weeklypull.py:1619-1803`); one-off downloads of pull
issues without watching the series (`oneoffhistory` table); auto-mass-add of configured
publishers (`MASS_PUBLISHERS` / `AUTO_MASS_ADD`); optional weekly folder
(`WEEKFOLDER`/`WEEKFOLDER_LOC`/`WEEKFOLDER_FORMAT`).

## 2. Story arcs / reading lists

**Model**: `storyarcs` table (`__init__.py:799,822`) — one row per arc issue: `StoryArcID`
(internal), `CV_ArcID` (ComicVine 4045- id), `IssueArcID`, `IssueID`/`ComicID` (library link),
`ReadingOrder`, `Status`, `Location`, `Manual`, `ArcImage`, dates, publisher, aliases.
(Historic table name `readinglist` is migrated.) Separate `readlist` table = per-issue reading
list with device-sync status (`readinglist.py`).

**Adding**: main path `addStoryArc()` (`webserve.py:1515`) imports an arc by CV arc ID —
fetches arc metadata + issue list with reading order via `mb.storyarcinfo()`/`cv.getComic
(rtype='issue', arclist)`, downloads a banner image, resolves per-series year/publisher/type,
upserts issues, then runs `ArcWatchlist()` to match against the library. **CBL (ComicRack
reading list) import** is a two-step validate/process flow (`webserve.py:9512,9619`) that adds
missing volumes to the watchlist and marks existing issues Wanted (honors
`CBL_IMPORT_ISSUESONLY`/`IGNOREARCHIVED`). Arc refresh = `addStoryArc(arcrefresh=True)`,
manual issues and reading-order edits supported (`webserve.py:4877,4985`).

**Library mapping vs arc directories** (`ArcWatchlist()`, `webserve.py:5253`): matches arc
issues to library series by DynamicComicName + Int_IssueNumber with an issue-date equality
check to reject wrong volumes. If `STORYARCDIR` is on, arcs get their own directory under
`STORYARC_LOCATION` (or `DESTINATION_DIR/StoryArcs`) formatted by `ARC_FOLDERFORMAT`
(default `($arc) ($spanyears)`; tokens `$arc/$spanyears/$publisher`; `helpers.py:2898-2940`);
owned files are copy/move/hard-/softlinked in per `ARC_FILEOPS` (default copy), optionally
prefixed with reading order (`READ2FILENAME`). A `cvinfo` URL file is written per arc dir.

**Arc-driven wanted issues**: `ReadGetWanted()` (`webserve.py:5614`) marks non-owned arc
issues Wanted — **including series not in the library** (standalone one-off search built from
arc row data) — and pushes them onto `SEARCH_QUEUE`; the Auto-Search job also sweeps
`storyarcs WHERE Status='Wanted'` (`search.py:1656-1661`). `addMissingSeriesFromArc()`
bulk-adds all arc series to the watchlist (`webserve.py:9411`). There is **no scheduled arc
refresh job** — refresh is manual/on-page-load only.

## 3. Search / wanted-issue scheduling

**Statuses**: Skipped, Wanted, Snatched, Downloaded, Archived, Failed, Ignored, Incomplete
across `issues`/`annuals`/`storyarcs`/`weekly` tables. Issues become Wanted via watchlist
refresh of upcoming issues, weekly-pull matching, arc wanting, or manual UI/API actions.

**Backlog job**: APScheduler job "Auto-Search" (`__init__.py:504-505`), interval
`SEARCH_INTERVAL` default **1440 min, clamped min 360** (`config.py:1324-1326`).
`searchforissue()` (`search.py:1521`) collects Wanted (and Failed, when `FAILED_AUTO`) rows
from `issues` + `storyarcs` + `annuals`, re-validates each (`searchforissue_checker`,
`search.py:4267`), sorts **newest StoreDate first**, and applies **tiering**: items added
within `SEARCH_TIER_CUTOFF` days (default 14) are Tier-1 and enqueued to `SEARCH_QUEUE`;
older Tier-2 items are skipped that pass (`search.py:1907-1930`). A global `SEARCHLOCK`
serializes searching one issue at a time with a 5s inter-item sleep (`helpers.py:3492-3547`);
the queue worker also short-circuits to post-processing if the file already exists locally.

**RSS pipeline**: job "RSS Feeds" every `RSS_CHECKINTERVAL` (default/min **20 min**).
`rsscheck` polls: public torrent feeds (Demonoid, WorldWideTorrents), 32P feeds (new-releases
or per-account notification feeds), every enabled newznab host's `/rss`, nzbindex.nl
("Experimental"), and DDL feeds; entries are normalized (title parsed by filechecker) and
cached in the `rssdb` table (`rsscheck.py:639-688`). After caching, a search pass in RSS mode
matches wanted issues **against the local rssdb via SQL join** — an RSS hit is snatched
straight from cache with no live indexer query; only unmatched issues fall through to API
search (`search.py:184-204, 2003-2059`).

**Provider rotation**: enabled providers (32P, public torrents, torznabs, experimental,
newznabs, DDL/GetComics, DDL/External) are assembled (`search.py:557-625`), ordered by the
user-defined `PROVIDER_ORDER` map (`search.py:2602-2617`), and walked in order per issue with
zero-padding variants of the issue number; stop on first hit. Per-provider state persists in
`provider_searches` (lastrun, hits) (`__init__.py:827`, `search.py:4087-4124`); single-shot
providers aren't re-hit within a run; temporary provider blocks via `block_provider_check`;
inter-search delay `SEARCH_DELAY` (default 1 min, 30s for manual).

**Retry / failed handling**: `failed` table + `Failed.FailedProcessor` — failed downloads mark
the issue `Failed` and blacklist the provider result ID; `failed_check()` rejects known-bad
result IDs pre-snatch (NZBHydra GUIDs normalized) (`Failed.py:246-288`); `FAILED_AUTO`
re-queues an immediate retry search excluding the bad result. Failed handling does **not** yet
cover story arcs/one-offs (`Failed.py:184`).

**Result evaluation** (`search_filer.py`): junk-word/except-list filtering, user
`IGNORE_SEARCH_WORDS`, min/max size limits (`USE_MINSIZE`/`MAXSIZE`), booktype match
(issue/TPB/HC/GN/One-Shot unless ignored), then a full filechecker parse+`matchIT()` of the
release title for series/issue/volume/year (±tolerance), pack preference, first-acceptable
selection.

## 4. Post-processing

**Four pickup paths**:
1. **External scripts → API**: `post-processing/{sabnzbd,nzbget}/ComicRN.py` →
   `autoProcessComics.py` → `api?cmd=forceProcess` with nzb_name/folder/failed
   (`autoProcessComics.py:73-85`, `api.py:886`).
2. **Completed Download Handling (CDH)** — Mylar polls SAB/NZBGet itself: snatches are put on
   `NZB_QUEUE`; `helpers.nzb_monitor` polls the client queue+history APIs until
   complete/failed (`sabnzbd.py:78-316`, `nzbget.py:133-311`), detects double-PP (ComicRN
   still configured) and refuses, and remaps remote client paths to local paths via
   `cdh_mapping.CDH_MAP` (`cdh_mapping.py:23`). Success is CRC-checked then queued to
   `PP_QUEUE`.
3. **Folder monitor**: scheduled `FolderCheck` every `DOWNLOAD_SCAN_INTERVAL` (5 min) runs a
   Manual-Run PP over `CHECK_FOLDER` (`PostProcessor.py:3568-3597`).
4. **DDL queue** hands completed direct downloads to PP with `[__issueid__]` filename tags.

**Snatch↔download handshake**: at snatch time `updater.nzblog()` records
`(IssueID, NZBName, AltNZBName, provider, ID, SARC, OneOff)` (`updater.py:844-891`); at PP
time the nzb name is normalized and matched against `nzblog` (fallback: parens-stripped, then
`mode='outside'` filename-parse manual PP) (`PostProcessor.py:2019-2065`); entry deleted after
success. One-offs use synthetic IssueIDs ≥900000; arc downloads use `'S'+IssueArcID`.

**Metadata tagging** (`cmtagmylar.py` + bundled `comictagger.py` wrapper): ComicTagger is run
as a **subprocess** on a temp copy — first an export pass converting **CBR→CBZ** (with
`--delete-rar` in move mode, corrupt-archive detection), then up to two tagging passes writing
**ComicRack (ComicInfo.xml)** and/or **CBL** tag blocks (`CT_TAG_CR`/`CT_TAG_CBL`), sourcing
metadata from ComicVine by `--id <issueid>` (fallback filename mode), injecting volume,
story-arc name + reading order, and age rating via `-m` (`cmtagmylar.py:88-221`). Config:
`CBR2CBZ_ONLY`, `CT_CBZ_OVERWRITE`, `CT_NOTES_FORMAT` (CVDB/Issue ID), `CT_SETTINGSPATH`,
`CMTAG_VOLUME`, `CMTAG_START_YEAR_AS_VOLUME`, `UNRAR_CMD`. Existing-library tagging: per-issue
`manual_metatag`, series-wide `group_metatag` (threaded, with **CV batch-limit protection**
threshold), mass metatag across series (`webserve.py:7947-8178, 4494-4557`).

**Moving/renaming**: folder path from `FOLDER_FORMAT` (default `$Series ($Year)`; tokens
`$Series/$series/$Publisher/$publisher/$Imprint/$Year/$VolumeY/$VolumeN/$Type`;
`filers.py:71-304`), file name from `FILE_FORMAT` (default `$Series $Annual $Issue ($Year)`;
adds `$Issue/$monthname/$month/$Annual`; `PostProcessor.py:3141-3196`). Options: zero-level
issue padding (`none/0x/00x`), lowercase filenames, replace-spaces char, illegal-char
stripping, per-series filename override, booktype in folder only for non-Print
(`FORMAT_BOOKTYPE`). Operations move/copy/**hardlink/softlink** (`FILE_OPTS`,
`helpers.py:4773-4903`; links disable metatagging), with cross-device fallback,
free-space guard, permission enforcement (`CHMOD_FILE/DIR`, `CHOWNER/CHGROUP`).

**Duplicate handling** (`helpers.duplicate_filecheck()`, `helpers.py:2231`): triggers only
when the issue is already Downloaded/Archived; `DUPECONSTRAINT` = prefer-cbz / prefer-cbr /
**filesize (keep larger, default)**; explicit "fixed" release markers `(f1)/(f2)` always win;
losing file optionally moved to a **duplicate dump folder** (`DDUMP`/`DUPLICATE_DUMP`,
optional dated subfolders).

**Failed PP**: SAB/NZBGet failure, CRC failure, or corrupt archive from ComicTagger routes to
`FailedProcessor` (mark Failed + blacklist + optional auto-retry search) (`process.py:52-88`).

**Script hooks**: pre-scripts (before tag/move), extra-scripts (after PP), on-snatch script
with `mylar_*` env vars, all with shell-location selection and PowerShell awareness
(`PostProcessor.py:113-191`, `helpers.py:3706-3746`).

**Library import** (`librarysync.py` + `webserve.py:6041-6289`): walks `COMIC_DIR`, parses
every cbr/cbz via filechecker (reads embedded ComicInfo where present), stages results in
`importresults` grouped by dynamic name, then an import UI supports mass import / select /
recheck / metatag; series with embedded CV IDs import directly via `addbyid`, others get a CV
year+issue-range search; files optionally moved/renamed into the library (`IMP_MOVE`,
`IMP_RENAME`, `IMP_METADATA`, `IMP_PATHS`, `IMP_SERIESFOLDERS`); global `IMPORTLOCK`.

## 5. Torrents and non-DDL providers / download clients

**Usenet**: SABnzbd (add-by-URL — SAB fetches the nzb back **from Mylar's own API** with a
one-time download API key, `search.py:3416-3597`; queue/history polling; version-aware
history query; auto-delete completed/failed; API-key scrape helper `sabparse.py`), NZBGet
(XML-RPC append with priority/category, history verify ±5% size, `nzbget.py`), and
**blackhole** (drop .nzb into a dir, `search.py:3177-3239`). One NZB client at a time
(`NZB_DOWNLOADER` 0/1/2/3).

**Indexers**: unlimited **newznab** and **torznab** entries stored as 7-field tuples
`(name, host, verify_ssl, apikey, category, enabled, provider_id)` in
`EXTRA_NEWZNABS`/`EXTRA_TORZNABS` (`config.py:1669-1751`); `#`-delimited multi-categories;
`[local]`/`[nzbhydra]` host annotations; `USENET_RETENTION` maxage on newznab queries.

**Torrent trackers**: **32Pages** private tracker with full session login (cfscrape +
persisted cookie jar, inkdrops balance, personal notification RSS feeds, series-list search,
authenticated .torrent download, auto-disable on login failure to avoid bans — `auth32p.py`);
**WorldWideTorrents** scrape with Cloudflare cookie handling (`wwt.py`); **Demonoid** public
RSS; dead TPSE/TorrentProject code. `MINSEEDS` filter for public results.

**Torrent clients** (`TORRENT_DOWNLOADER`, one at a time): watch-dir (local or **seedbox via
SFTP upload** of the .torrent, `ftpsshup.putfile`), uTorrent (WebUI token API), rTorrent
(SCGI/HTTP-RPC + SSL + label + directory), Transmission (transmissionrpc, no labels), Deluge
(RPC, label auto-create, move-completed dir, add-paused), qBittorrent (category, savepath,
pause/force_start) — `mylar/torrent/clients/`, dispatch in `rsscheck.torsend2client`
(`rsscheck.py:1365-1465`).

**End-to-end torrent flow**: search match → fetch .torrent/magnet (tracker-authenticated or
Cloudflare-bypassed) → send to client → for rTorrent/Deluge an **AUTO-SNATCHER** worker
monitors the client for completion (`SNATCHED_QUEUE`, `helpers.py:3556`) and runs
`AUTO_SNATCH_SCRIPT` (shipped `getlftp.sh` — lftp/sftp pull from a seedbox using
`PP_SSH*` settings) → file lands locally → PP queue. On-snatch notify + snatch script env
vars include hash/label/folder.

**DDL mirror downloaders** (`mylar/downloaders/`): Mega (anonymous mega lib login),
MediaFire (redirect-chain scrape), Pixeldrain (API with captcha/rate-limit detection), plus
an optional "external server" (mega-backed) — these serve GetComics mirror links, tracked in
the `ddl_info` table with per-link-type failover. (GetComics main flow itself: other agent.)

## 6. Notifications

Ten agents in `notifiers.py`: **Prowl, Pushover, Boxcar, Pushbullet, Telegram, Slack,
Mattermost, Discord, Email (SMTP), Gotify**. Events: **on-snatch** (per-agent `_ONSNATCH`
gate; single-issue and pack variants; Mattermost defined-but-not-wired here —
`search.py:3711-3799`), **on post-process complete** (all ten, cover-image attachment for
Pushover/Telegram/Discord/Mattermost/Gotify — `PostProcessor.py:3519-3562`), and
**metatagging error** (all ten, `cmtagmylar.py:355+`). Weekly pull triggers nothing. Each
agent has a webserve test endpoint (`webserve.py:8197-8311`) and a Pushbullet device lister.
Cover thumbnails for notifications are extracted from the actual archive (`getimage.py`).

## 7. Config surface (config.ini schema)

`_CONFIG_DEFINITIONS` OrderedDict of `KEY: (type, Section, default)` (`config.py:34`),
**34 sections**: General (~79 keys: paths, refresh cadence, renaming, autowant, quality/size
gates, failed handling, covers/series.json, backups, backfill, UI toggles), Scheduler (5
interval keys), Weekly, Interface (host/port/HTTPS/auth/root), API, CV (rate, key,
ignored publishers, imprint mapping), Logs, Git, Perms, Import, Duplicates, 10 notifier
sections, PostProcess (script hooks, CDH, folders), Providers (`PROVIDER_ORDER`,
`USENET_RETENTION`), Client, SABnzbd, NZBGet, Blackhole, Newznab, Torznab, Experimental,
Tablet (device sync), StoryArc, Update, Metatagging, Torrents, DDL (incl. FlareSolverr +
proxy), AutoSnatch (+SSH), Watchdir, Seedbox, 32P, Rtorrent/uTorrent/Transmission/Deluge/
qBittorrent, OPDS, CBLImport.

Plumbing worth copying conceptually: **versioned stepped config migrations** (v6→v14/15:
torznab-list merge, provider IDs, DDL split, DOGnzb/NZBsu folded into newznab)
(`config.py:668-766`); **automatic config backup before upgrade** with retention
(`config.py:657-666`); **at-rest obfuscation of secrets** in the ini (salted-base64
`^~$z$` marker, explicit encryption list of ~25 credential keys — `config.py:1080-1104`,
`encrypted.py`); `MINIMAL_INI` mode writing only non-defaults; interval min-clamping.

## 8. Everything else notable

**Scheduled jobs** (APScheduler BackgroundScheduler, UTC, 20 workers, coalesce,
max_instances 3 — `__init__.py:228-235,500-522`): DB Updater (24h), Auto-Search (24h default,
min 6h), Weekly Pullist (4h fixed), RSS Feeds (20 min), Check Version (6h), Folder Monitor
(5 min). Job last-run/next-run persisted in the `jobhistory` table via
`helpers.job_management`; thin `*it.py` wrapper classes set Running/Waiting status. Worker
thread pools + queues: SEARCH_QUEUE, SNATCHED_QUEUE (torrent completion), NZB_QUEUE (CDH),
PP_QUEUE, DDL_QUEUE, plus a serialized DB-writer thread.

**Series metadata refresh**: the modern "DB Updater" job (`updater.watchlist_updater`,
`updater.py:2022`) polls ComicVine's *recently-updated volumes* feed since last run and
refreshes only changed series, with first-run **backfill** batching (1500 results/run,
`BACKFILL_LENGTH`/`BACKFILL_TIMESPAN`); legacy per-series `dbUpdate` guarded by
`REFRESH_CACHE` days; Continuing/Ended recalculation from latest-issue age (<55 days);
`forceRescan()` re-walks a series folder and recomputes Have/Total; optional per-series
`series.json` metadata files (`series_metadata.py`) and `cvinfo` URL files.

**DB**: SQLite `mylar.db`, ~24 tables (comics, issues, annuals, storyarcs, weekly, upcoming,
futureupcoming, oneoffhistory, snatched, nzblog, rssdb, failed, importresults, searchresults/
tmp_searches/manualresults, readlist, ddl_info, ref32p, jobhistory, provider_searches,
exceptions_log, notifs, mylar_info) with additive idempotent ALTER-TABLE migrations and a
retry-on-locked wrapper (`db.py`, `__init__.py:791-1587`).

**API** (`api.py`): apikey-authenticated command API, ~43 commands in `cmd_list` (library
CRUD, search forcing, status changes, provider CRUD, story arcs, covers/art, downloadNZB
handoff for SAB, version/update/restart/shutdown, SSE global messages); separate limited
**download API key** and **SSE key**; `getAPI` bootstrap via username/password.

**Web/auth**: CherryPy; auth modes none / HTTP Basic / **forms+session login** with timeout;
HTTPS with **self-signed cert auto-generation**; `/api` exempt (own key); OPDS gets its own
Basic-auth realm. Passwords optionally stored obfuscated.

**Cache**: cover artwork cache with 30-day freshness and old-version cleanup (`cache.py`);
archive page extraction + PIL resize for previews/notification thumbnails (`getimage.py`);
cache/stray cleanup options.

**Maintenance & ops**: rolling versioned backups of DB+config with retention
(`maintenance.py:356`); JSON export/import of the library; DB import from another mylar.db;
`clear_provider_table`; path-separator fixer; a **maintenance-mode mini web UI**
(`maintenance_webstart.py`); **carepackage** diagnostic zip with secrets stripped
(`carepackage.py`); git-based self-update with commits-behind detection and
source-tarball fallback (`versioncheck.py`); exception capture to DB; Docker/init scripts
(`Dockerfile`, `init-scripts/`).

**Reader-ish extras (out of foragerr scope by design)**: in-browser comic reader
(`webviewer.py`), reading-list device sync pushing files to a tablet over SFTP
(`readinglist.py:137`, `ftpsshup.sendfiles`, Tablet config section).

**Legacy metadata sources**: GCD scraper (`parseit.py`), ComicBookDB scraper
(`comicbookdb.py`), solicitations scraper feeding `futureupcoming` (`solicit.py`) — all
secondary to ComicVine.

---

# (a) CAPABILITY MAP

Areas marked **(new)** are proposed additions to the foragerr AREA table.

**SER — series/library management**
- Watchlist of series (add by CV search or CV ID; Active/Paused/Loading status; delete incl. optional folder removal)
- Per-series overrides: corrected series name/type, alternate search names, alternate file name, forced Continuing, per-series location + dir lock
- Annuals as first-class linked records (`annuals` table, `ANNUALS_ON`), annual↔series release links
- Have/Total issue counts; `forceRescan` folder re-walk recomputing statuses/locations
- Continuing/Ended auto-recalculation from latest-issue recency
- Issue status lifecycle: Skipped/Wanted/Snatched/Downloaded/Archived/Failed/Ignored
- Multiple destination dirs (`MULTIPLE_DEST_DIRS`), create-folders-on-add, maintain/lock series folders
- One-off issues (download without watching series; `oneoffhistory`)
- Auto-add series from new #1s on the pull (`future_check`) and mass-add by publisher

**META — metadata**
- ComicVine as primary metadata source (cv.py — covered by other agent; 1 req/s rate limit, ban detection, user-agent config)
- Incremental series refresh via CV recently-updated feed with backfill batching (watchlist_updater)
- ComicTagger subprocess integration: CBR→CBZ conversion, ComicInfo.xml (CR) + CBL tagging, CV id-based tagging, volume/arc/reading-order/age-rating injection
- Existing-library tagging: per-issue, per-series (threaded, CV batch-limit protection), mass across series
- `series.json` per-series metadata files; `cvinfo` URL files in series/arc folders
- Cover art download + 30-day cache; alternate latest-series covers; cover regeneration API
- Imprint mapping, ignored-publishers filter
- Legacy scrapers: GCD (parseit.py), ComicBookDB, publisher solicitations (solicit.py)

**IDX — indexers**
- Multiple newznab indexers (name/host/apikey/categories/verify/enabled tuples), NZBHydra + `[local]` awareness
- Multiple torznab indexers (same tuple shape)
- `USENET_RETENTION` maxage; multi-category per indexer; per-provider ID assignment
- "Experimental" provider: nzbindex.nl RSS scrape with zero-pad OR-queries
- Provider ordering (`PROVIDER_ORDER`), per-provider hit/lastrun tracking (`provider_searches`), temporary provider blocklist/cooldown
- Provider CRUD via API (listProviders/addProvider/delProvider/changeProvider)

**SRCH — search & wanted scheduling (new)**
- Periodic backlog search of all Wanted issues (issues+annuals+storyarcs), newest-first, two-tier recency prioritization (`SEARCH_TIER_CUTOFF`)
- Serialized search queue (one issue at a time, inter-search delay), pre-search local-file short-circuit
- RSS mode: poll provider feeds into `rssdb` cache, match wanted issues offline against cache, snatch from cache; API search only for RSS misses
- Result scoring: name/issue/volume/year match via filename parser, booktype check, min/max size, ignore-words, pack preference
- Failed-result blacklist checked pre-snatch; auto-retry on failure (`FAILED_AUTO`)
- Manual per-issue search, one-off pull search, arc search, searchIssueIDList batch
- Issue-number variant generation (zero-padding permutations)

**PULL — weekly pull list**
- Weekly release data from walksoftly/LOCG JSON API (current + previous week), backend-status tracking
- `weekly` table with per-week wipe/rebuild; upcoming + futureupcoming tables
- Matching to watchlist by CV ID, annual ID, and normalized-name+sequence heuristics; date-window safety check; booktype guard
- Auto-want matched upcoming issues (`AUTOWANT_UPCOMING`/`AUTOWANT_ALL`); forced series refresh when pull issue missing locally
- 4-hourly refresh job + manual recreate; pull pagination reset; weekly one-off downloads; weekly folder option
- Future-release watching (add2futurewatchlist) and auto-add of new #1s

**ARC — story arcs**
- Arc import by ComicVine arc ID with reading order + banner image; arc refresh; manual arc issues; reading-order editing
- CBL (ComicRack) reading-list import (validate + process; add volumes / want issues)
- Arc↔library matching with wrong-volume date guard; arc progress (have/total)
- Optional dedicated arc directories with own folder format and copy/link file-ops; reading-order filename prefix
- Arc-driven Wanted searches including series not in the library; bulk add-missing-series-from-arc

**DL — usenet download clients**
- SABnzbd: add-by-URL (client pulls nzb from Mylar's API with one-time download key), priority/category, queue+history polling, double-PP detection, remove-completed/failed, API-key scrape helper, version check
- NZBGet: XML-RPC append (base64), priority mapping, history verification with size tolerance, double-PP detection
- Blackhole .nzb drop directory
- Completed Download Handling (client polling; no external script needed) + remote-path remapping (cdh_mapping)

**TOR — torrents**
- Private tracker 32P: session login with cookie persistence, Cloudflare scraping, inkdrops, personal notification feeds, series-list + group search, authenticated download, auto-disable on auth failure
- Public trackers: WWT scrape+RSS, Demonoid RSS; minimum-seeders filter
- Clients: watchdir (local or SFTP-to-seedbox), uTorrent, rTorrent (SCGI/SSL/labels), Transmission, Deluge (labels/pause/move-completed), qBittorrent (category/pause/force-start)
- Auto-snatch: monitor rTorrent/Deluge for completion, run fetch script (bundled lftp/sftp seedbox harvester), hand to PP
- Magnet + .torrent handling, hash computation, on-snatch script env vars

**DDL — direct download** *(other agent: getcomics.py internals)*
- GetComics search/scrape + DDL queue with resume, pack priority, FlareSolverr + proxy support (one-line: covered elsewhere)
- Mirror-link downloaders with failover: Mega, MediaFire, Pixeldrain, optional external mega-backed server; `ddl_info` tracking

**PP — post-processing (new)**
- Four intake paths: external client scripts→API, client polling (CDH), watched-folder scan job, DDL handoff
- nzblog snatch↔completion handshake (name normalization + AltNZBName), fallback filename-parse "outside" PP
- Metadata tagging on import (see META), CRC/file-condition verification
- Renaming: FILE_FORMAT/FOLDER_FORMAT token engines, zero-padding, lowercase, space replacement, annual/booktype/volume handling
- File ops: move/copy/hardlink/softlink with cross-device fallback, free-space guard, permissions/ownership enforcement
- Duplicate handling: cbz/cbr/filesize constraint, fixed-release override, duplicate dump folder (dated)
- Failed-download PP: mark+blacklist+optional auto-retry
- Pre/extra/on-snatch script hooks with env-var contract; manual PP of arbitrary folder

**IMP — library import**
- Recursive library scan, filename parse + embedded-metadata read, `importresults` staging grouped by series
- Import queue UI: mass import, select, recheck, metatag; direct add-by-ID for CV-tagged files; CV identification search for the rest
- Optional move/rename during import; skip-known-paths; import lock

**OPDS** *(other agent)*
- OPDS catalog server with own Basic-auth realm, pagination, metainfo (one-line: covered elsewhere)

**UI — web interface**
- CherryPy + Mako UI: watchlist index, series detail, pull list, upcoming, wanted, history, import results, arc pages, manage tab, config forms, logs viewer
- Manual search/one-off buttons, annual management, status batch changes, provider tests, notification tests
- Alpha index, icons toggle, interface selection; in-browser comic reader (webviewer)
- Global messages / SSE notification stream (`notifs` table, SSE key)

**API**
- ~43-command apikey API (library CRUD, search, status, providers, arcs, art, system) + forceProcess PP entrypoint + downloadNZB
- Tiered keys: full API key, download-only key, SSE key; getAPI bootstrap from credentials

**DB**
- SQLite, ~24 tables, additive idempotent migrations, DB version row, locked-retry wrapper, dedicated writer thread
- Rolling versioned DB+config backups with retention; JSON library export/import; DB import tool

**AUTH — authentication/security**
- Web auth modes: none / HTTP Basic / form+session with login timeout; HTTPS incl. self-signed cert generation
- Per-surface auth: API keys separate from web login; OPDS separate credentials
- At-rest credential obfuscation in config.ini (salted base64, marker-prefixed)
- Secrets-stripped diagnostic bundle (carepackage)

**NOTIF — notifications**
- Agents: Prowl, Pushover, Boxcar, Pushbullet, Telegram, Slack, Mattermost, Discord, Email, Gotify
- Events: on-snatch (per-agent opt-in), on post-process complete, on metatagging error; cover-image attachments where supported
- Per-agent test endpoints; Pushbullet device enumeration

**SCHED — job scheduling (new)**
- APScheduler background jobs: DB updater, auto-search, weekly pull, RSS, version check, folder monitor; interval clamping
- Persistent job history (prev/next run, status) surviving restarts; force-run from UI
- Worker queues/pools: search, snatched-monitor, nzb-monitor, post-process, DDL

**DEP — deployment/ops**
- Dockerfile + init scripts (systemd/init.d); git self-update with commits-behind check and tarball fallback; version check job
- Config versioned migrations + pre-upgrade auto-backup; MINIMAL_INI; cache cleanup; exception log table; carepackage diagnostics; maintenance mode web UI

**READ — reading/device sync (new; foragerr likely out of scope)**
- Reading list (readlist) with read/unread state; device sync over SFTP to tablet; in-browser reader

*(Excluded deep areas, one line each: **filename parsing** — filechecker.py dynamic-name parser used everywhere above; **ComicVine client** — cv.py; **DDL** — getcomics.py scraper/downloader; **OPDS** — opds.py catalog server.)*

---

# (b) Candidate requirements (plain prose, areas covered here)

**Weekly pull (PULL)**
- The system shall fetch weekly release lists on a schedule from a configurable release-data source, covering at least the current and previous release week, and shall surface source-outage status to the user rather than failing silently.
- The system shall match pull-list entries to watched series primarily by ComicVine ID, with a guarded name-based fallback that validates issue-number sequence and release-date proximity before accepting a match.
- The system shall optionally mark matched upcoming issues as Wanted automatically, and shall trigger a metadata refresh for a watched series when a pulled issue is not yet present in its local issue list.
- The system shall record per-week pull status per entry (skipped/wanted/snatched/downloaded) and allow manual want/skip/search actions from the pull view.

**Story arcs (ARC)**
- The system shall import a story arc by ComicVine arc ID, storing ordered issue entries with reading order and linking each to library series/issues where present.
- The system shall compute arc completion (owned vs total) and allow marking missing arc issues as Wanted, including issues from series not in the library, feeding the normal search pipeline.
- The system shall optionally materialize an arc as a directory of copies/links of owned files using an arc-specific folder format, without disturbing the canonical library files.

**Search scheduling (SRCH)**
- The system shall periodically search for all Wanted issues, prioritizing recently added ones, serializing searches with a configurable inter-search delay to respect indexer limits.
- The system shall support an RSS fast-path: poll enabled provider feeds into a local cache on a short interval and satisfy Wanted issues from the cache before issuing live indexer queries.
- The system shall evaluate candidate releases against series name, issue number, volume, year, book type, and configurable size bounds and ignore-words before snatching.
- The system shall try providers in a user-defined order, stop at the first accepted result, track per-provider usage, and temporarily block failing providers.
- The system shall record failed downloads, exclude previously failed release IDs from future selection, and optionally auto-retry the search excluding the failed result.

**Post-processing (PP)**
- The system shall detect completed downloads without external client scripts by polling the download client's queue/history API, mapping remote client paths to local paths when the client runs on another host.
- The system shall reconcile completed downloads to snatched issues via a persisted snatch log keyed by release name and issue ID, with a filename-parse fallback for unmatched folders.
- The system shall convert CBR to CBZ and write ComicInfo.xml metadata sourced from ComicVine (via ComicTagger or equivalent), on both new downloads and, on demand, across the existing library with API-rate protection.
- The system shall rename and place files according to configurable folder and file format templates (series/year/volume/issue tokens, zero-padding, case and separator options) and support move/copy/hardlink/softlink operations with free-space and permission enforcement.
- The system shall detect duplicates at import time and resolve them by a configurable constraint (preferred format or larger file), optionally preserving the losing file in a dump folder.
- The system shall verify archive integrity before accepting a download and route corrupt/failed items to failed-download handling.

**Torrent/usenet clients (DL/TOR)** *(foragerr scope is SABnzbd + DDL; these are candidates only if scope widens)*
- The system shall send accepted NZB results to SABnzbd with category and priority and confirm final status from SABnzbd history, distinguishing success, failure, and still-processing states.
- The system shall prevent double post-processing when an external completion script and built-in polling are both configured.

**Notifications (NOTIF)**
- The system shall emit notification events on snatch and on completed post-processing, with per-channel enablement and per-event opt-in, through at least one push channel (e.g. webhook/Discord/Telegram/email), and provide a test action per channel.

**Config (DEP/DB)**
- The system shall store configuration with a schema version and apply stepped migrations on upgrade, taking an automatic retained backup of configuration and database before migrating.
- The system shall never persist credentials in plain text in exportable diagnostics, and shall redact API keys from logs.

**Scheduling/core (SCHED/API/AUTH)**
- The system shall run its periodic jobs (metadata refresh, pull refresh, search, RSS, completed-download scan) on configurable intervals with persisted last-run/next-run state surviving restarts, and allow forcing any job from the UI/API.
- The system shall refresh series metadata incrementally by querying the metadata source's changed-since feed rather than re-fetching every series.
- The system shall expose an API protected by an API key distinct from web-session auth, including a restricted-scope key usable only for file download handoff to the download client.

---

*Prepared read-only per FRG-PROC-008; staged outside the repository. Source: six sub-agent
surveys of `.reference/mylar3` (weeklypull/arcs; search/rss; PostProcessor/import; torrent/
clients; config/notifiers; core/API/DB/jobs), 2026-07-04.*
