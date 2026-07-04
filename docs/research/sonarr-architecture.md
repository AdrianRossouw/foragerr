# Sonarr Architecture Study for foragerr

Research deliverable. Source: `/Users/adrian/Projects/foragerr/.reference/sonarr` (studied read-only;
all paths below are relative to `src/` unless noted). Purpose: extract the behaviors and
architecture foragerr should imitate for a comic-shaped domain (ComicVine volumes/issues,
Newznab-only indexers, SABnzbd + DDL, SQLite/FastAPI/asyncio). We are not porting code.

Comic-domain translation used throughout: **Series → comic series/volume (ComicVine volume)**,
**Episode → issue**, **Season → mostly collapses away** (comics are effectively single-season;
where Sonarr has a season layer we note whether foragerr needs it).

---

## 1. Domain model: series / season / episode lifecycle, monitored flags, quality

### 1.1 Entities

- **Series** (`NzbDrone.Core/Tv/Series.cs`): external IDs (TvdbId etc.), `Title`, `CleanTitle`
  (normalized for matching), `SortTitle`, `TitleSlug`, `Monitored` (bool),
  `MonitorNewItems` (`NewItemMonitorTypes` = All|None — governs whether newly discovered
  seasons are auto-monitored), `SeriesType` (Standard/Daily/Anime — drives parsing and search
  strategy), `Status` (Continuing/Ended/Upcoming/Deleted, `Tv/SeriesStatusType.cs`),
  `QualityProfileId`, `Path`, `RootFolderPath`, `Tags`, `Added`, `LastInfoSync`, and a
  transient `AddOptions` cleared after the add flow completes.
- **Season** (`Tv/Season.cs`): *not a table* — an embedded document (`SeasonNumber`,
  `Monitored`, `Images`) serialized as JSON on the Series row (`Datastore/TableMapping.cs`).
  Series+seasons = one row; episodes are a separate table.
- **Episode** (`Tv/Episode.cs`): `SeriesId`, `EpisodeFileId` (0 = no file; `HasFile =>
  EpisodeFileId > 0`), `SeasonNumber`, `EpisodeNumber`, `Title`, `AirDate`/`AirDateUtc`,
  `Monitored`, `AbsoluteEpisodeNumber`, scene-numbering fields, `LastSearchTime`.
  "Wanted/missing" is **derived**: monitored + aired + no file — there is no stored
  per-episode wanted status.

**Comic mapping**: Series→ComicSeries (ComicVine volume id, title, publisher, start year, status
continuing/ended), Episode→Issue (issue number — note comics need *decimal/string* issue numbers:
`1`, `1.5`, `1.MU`, annuals — cover date, title, `IssueFileId`, `Monitored`). Drop the season
layer entirely, or keep a vestigial single "volume" grouping; Sonarr's embedded-season trick shows
a middle tier does not deserve its own table even if you keep one.

### 1.2 Lifecycle: add → refresh → scan → search

Sonarr's add flow is a chain of events, and it is worth copying exactly:

1. **Add** (`Tv/AddSeriesService.cs`): fetch remote metadata by external id (SkyHook proxy,
   `MetadataSource/SkyHook/SkyHookProxy.cs`, behind `IProvideSeriesInfo.GetSeriesInfo(id) →
   (Series, List<Episode>)`), apply user overrides (`Series.ApplyChanges` copies only
   user-editable fields), build `Path` from root folder + folder-name template if absent, compute
   `CleanTitle`/`SortTitle`, validate (path, root folder, slug uniqueness,
   `Tv/AddSeriesValidator.cs`), insert. `AddOptions` carries `Monitor` (a `MonitorTypes` value)
   plus `SearchForMissingEpisodes` / `SearchForCutoffUnmetEpisodes`.
2. **SeriesAddedEvent → RefreshSeriesCommand** (`Tv/SeriesAddedHandler.cs`).
3. **Refresh** (`Tv/RefreshSeriesService.cs`): re-fetch metadata, copy onto series, reconcile
   seasons (new seasons monitored iff `MonitorNewItems == All`; specials/season-0 forced
   unmonitored), then **episode reconciliation** (`Tv/RefreshEpisodeService.cs`): match remote
   episodes to local by (season, episode) key; insert new (monitored inherited from their
   season), update matched (metadata fields copied over), **delete local episodes absent from
   remote**. New-series safety: episodes aired more than a day ago on a just-added series are
   unmonitored unless the add options say otherwise (`UnmonitorReaddedEpisodes`).
   Scheduled refresh: every 12 h (`Jobs/TaskManager.cs`), but per-series skip logic
   (`Tv/ShouldRefreshSeries.cs`): skip if synced <6 h ago; always refresh if >30 days stale or
   an aired episode is still "TBA"; ended series only refresh if they aired within 30 days.
4. **Refresh → disk rescan → post-add monitoring + search** (`Tv/SeriesScannedHandler.cs`):
   after the first scan, apply `MonitoringOptions` per-episode, publish add-completed, queue the
   requested missing/cutoff-unmet searches, then clear `AddOptions`.

### 1.3 Monitored flags

Three levels, all plain booleans, reconciled by `Tv/EpisodeMonitoredService.cs`:
`MonitorTypes` (`Tv/MonitoringOptions.cs`) = All / Future / Missing / Existing / FirstSeason /
LastSeason / Pilot / Recent / MonitorSpecials / UnmonitorSpecials / None / Skip. The service sets
per-episode monitored per the chosen strategy, then derives each season's monitored from "has any
monitored episode". Series `Monitored` is an independent master switch (both series and episode
must be monitored for RSS auto-grab — see `DecisionEngine/Specifications/RssSync/MonitoredEpisodeSpecification.cs`).

**Comic mapping**: keep the two-level version — series `Monitored` + per-issue `Monitored`, with
add-time strategies "all / future issues only / missing / existing / none". `MonitorNewItems`
translates directly: when a metadata refresh discovers newly published issues, monitor them iff
the series says so. This is the single most load-bearing domain behavior to copy.

### 1.4 Quality model — and how much survives for comics

- `Qualities/Quality.cs`: a closed enum-like registry of ~22 qualities, each with static
  default `Weight` (global ordering), `MinSize`/`MaxSize`/`PreferredSize` (MB per minute of
  runtime) in `DefaultQualityDefinitions`.
- `Profiles/Qualities/QualityProfile.cs`: named profile = ordered list of
  `QualityProfileQualityItem`s (each `Allowed` yes/no, optionally grouped, with per-profile
  size overrides), a `Cutoff` (stop upgrading once met), `UpgradeAllowed`, and custom-format
  score thresholds (`MinFormatScore`, `CutoffFormatScore`).
- `Qualities/QualityModel.cs` + `Revision.cs`: a release's quality = Quality + Revision
  (`Version` for propers, `Real`, `IsRepack`). Upgrade comparisons use the **profile-order-aware**
  `Qualities/QualityModelComparer.cs` (profile item index first, then revision), not global weight.
- CustomFormats (`CustomFormats/`) are a parallel scored-tag system: regex/attribute conditions
  produce a score per release; profiles set min/cutoff scores; score participates in upgrade
  decisions and prioritization.

**How much translates to comics**: the *ladder* mostly does not — comics have no
resolution/source hierarchy. What survives:
- **Format preference** as a tiny quality ladder: e.g. `cbz > cbr > pdf/epub`, maybe
  `digital (c2c) > scan`. Two to five rungs, profile-ordered, with a cutoff ("stop at cbz").
- **Revision/proper semantics**: comics get "fixed"/re-released scans (v2, "(fixed)"); keep a
  small revision counter so a fixed release upgrades the same rung.
- **Size sanity bounds**: per-format min/max MB per issue (Sonarr scales by runtime; comics can
  scale by page count from ComicVine, or just use flat bounds). This backs
  `AcceptableSizeSpecification`.
- **Custom-format scoring** is the more useful half for comics: preferred release groups
  (e.g. digital groups), preferred terms ("c2c", "HD"), avoided terms — a scored tag system is a
  better fit than a deep quality tree. Recommend: shallow quality ladder + term/group scoring.

---

## 2. Indexer abstraction (Newznab/Torznab)

### 2.1 Provider pattern ("ThingiProvider")

All pluggable providers (indexers, download clients, notifications, import lists) share one
pattern (`NzbDrone.Core/ThingiProvider/`): a `ProviderDefinition` DB row (`Name`,
`Implementation` class name, `ConfigContract`, serialized `Settings` JSON, `Tags`) + a
`ProviderFactory` that instantiates the implementation from DI, attaches the definition, and
filters to valid/enabled instances. `Indexers/IndexerDefinition.cs` adds `Protocol`,
`Priority` (default 25), and the three per-indexer toggles **`EnableRss` /
`EnableAutomaticSearch` / `EnableInteractiveSearch`** (`IndexerFactory.RssEnabled()` etc. filter
on them). This settings-as-serialized-contract pattern is what powers the dynamic settings UI
(§7) — imitate it: one `indexers` table with `implementation` + JSON settings, one
`download_clients` table likewise.

### 2.2 Indexer interface

`Indexers/IIndexer.cs` / `IndexerBase.cs` / `HttpIndexerBase.cs`:
- `FetchRecent()` (RSS) and `Fetch(criteria)` per search-criteria type; each indexer supplies an
  `IIndexerRequestGenerator` (builds URL request chains) and an `IParseIndexerResponse`
  (response → `List<ReleaseInfo>`).
- `HttpIndexerBase.FetchReleases` is the core loop: request chain has **tiers** (try id-based
  search first; only fall to title tier if a tier yields nothing), paging within each request
  (`offset`/`limit`, max ~30 pages, hard cap 1000 results), per-indexer rate limiting (2 s),
  and RSS-gap detection using the last-seen release bookmark
  (`IndexerStatusService.GetLastRssSyncReleaseInfo`).
- `IndexerBase.CleanupReleases`: de-dupe by `Guid`, stamp `IndexerId`/`Indexer`/`Protocol`/
  `IndexerPriority` on every release.

### 2.3 Newznab specifics (`Indexers/Newznab/`)

- **Capabilities** (`NewznabCapabilitiesProvider.cs`): `?t=caps` fetched and cached 7 days;
  advertises supported search params (`q`, `tvdbid`, `season`, `ep`, `title`), page-size limits,
  and the category tree. The request generator consults caps to decide *which* query form to emit.
- **Requests** (`NewznabRequestGenerator.cs`): RSS = `t=tvsearch` (or `t=search`) with `cat=`
  and no query. Searches emit id-based params when supported (`tvdbid`, aggregated ids), else
  **fall back to `q=` text search with cleaned titles** (`&`→`and`, non-word→`+`). Paging via
  `&offset=&limit=`. Category list empty ⇒ no requests at all.
- **Parsing** (`NewznabRssParser.cs`): RSS items → `ReleaseInfo`; `<error code>` mapped to
  ApiKeyException / RequestLimitReached; `newznab:attr` extras (ids, flags) captured.
- **Settings** (`NewznabSettings.cs`): BaseUrl, ApiPath, ApiKey, Categories (default TV
  5030/5040), AdditionalParameters; category options populated live from caps via a provider
  "action" endpoint.

**Comic note**: DogNZB/NZB.su have no `t=booksearch`-for-comics ids that match ComicVine, so
foragerr's request generator is essentially Sonarr's **`q=` fallback tier + `cat=7030`
(Books/Comics)** all the time. Keep the caps probe (page size, category list), the tiered
generator shape (so smarter query forms can be added later), the paging loop, and the per-indexer
category setting. Torznab is the same protocol over torrents — out of scope for foragerr but the
abstraction costs nothing.

### 2.4 Search types

Three distinct entry paths, one decision engine:
- **RSS sync** (`Indexers/RssSyncService.cs`, `FetchAndParseRssService.cs`): scheduled
  (`RssSyncCommand`, config-driven interval, default 15 min, min 10, 0 disables —
  `Jobs/TaskManager.cs`, `Configuration/ConfigService.cs`). Fans out `FetchRecent()` over all
  RSS-enabled indexers in parallel, swallows per-indexer errors, feeds everything +
  pending releases to `GetRssDecision` → `ProcessDownloadDecisions`.
- **Automatic search** (`IndexerSearch/ReleaseSearchService.cs`): triggered by commands
  (EpisodeSearch, SeasonSearch, MissingEpisodeSearch, CutoffUnmetEpisodeSearch) — e.g. after
  add, after failed download, from Wanted screens. Uses `AutomaticSearchEnabled()` indexers,
  builds per-type criteria, auto-grabs the best accepted release.
- **Interactive search**: same service with `interactiveSearch: true` — uses
  `InteractiveSearchEnabled()` indexers, relaxes monitored-only filtering, and **returns all
  decisions including rejected ones with reasons** to the UI instead of grabbing
  (`Sonarr.Api.V3/Indexers/ReleaseController.cs`). Flags travel on
  `SearchCriteriaBase.UserInvokedSearch/InteractiveSearch` and several specs (delay, monitored)
  short-circuit for user-invoked searches.
- Search results are de-duped by release Guid preferring fewest rejections then higher indexer
  priority (`ReleaseSearchService.DeDupeDecisions`).

### 2.5 Release parsing & mapping

- `Parser/Model/ReleaseInfo.cs`: guid, title, size, downloadUrl, indexer info, publish date,
  age accessors.
- Title → `ParsedEpisodeInfo` via a large regex battery (`Parser/Parser.cs`), then
  `Parser/ParsingService.cs.Map(...)` resolves the **Series** (by clean title / alias / year,
  with scene-mapping aliases) and the concrete **Episodes**, producing a `RemoteEpisode`
  (release + parsed info + series + episodes). Mapping failures become *rejected decisions*, not
  exceptions: `UnknownSeries`, `UnknownEpisode`, `UnableToParse`
  (`DecisionEngine/DownloadDecisionMaker.cs`).

**Comic mapping**: this is foragerr's hardest parser problem — release titles like
`Series.Name.015.(2024).(digital).(Group).cbz`. Copy the shape: pure-function title parser →
`ParsedIssueInfo` (series title, issue number, year, format/tags, group) → mapping service that
resolves against library clean-titles + user-editable aliases, failures as rejection reasons.

### 2.6 Indexer health / back-off

`ThingiProvider/Status/ProviderStatusServiceBase.cs` + `EscalationBackOff.cs`: on failure,
escalate through a back-off ladder (0 s, 1 m, 5 m, 15 m, 30 m, 1 h, 3 h, 6 h, 12 h, 24 h),
setting `DisabledTill`; success de-escalates one level. Rate-limit responses (Retry-After)
fast-forward the level. Blocked indexers are filtered out of RSS and search
(`Indexers/IndexerFactory.cs FilterBlockedIndexers`) and there is a matching *temporary*
decision rejection (`BlockedIndexerSpecification`). Copy verbatim — it is what keeps a flaky
indexer from wedging the whole pipeline.

---

## 3. Decision engine

### 3.1 Specification pattern

`DecisionEngine/DownloadDecisionMaker.cs`: every candidate release → parse → map → aggregate →
run **all registered specifications** (`IDownloadDecisionEngineSpecification`,
`Specifications/IDownloadDecisionEngineSpecification.cs`): each spec returns Accept or
`Reject(reason, message)` and declares:
- `RejectionType`: **Permanent** vs **Temporary** (`RejectionType.cs`) — temporary-only
  rejections make a decision *temporarily rejected* → it goes to the **pending queue** instead
  of being discarded (delay profiles work this way).
- `SpecificationPriority` (Default/Database=0, Disk=1): specs run grouped by priority; once a
  group rejects, cheaper groups already ran and expensive (disk) specs are skipped.

`DownloadDecision`: `Approved` = no rejections; `TemporarilyRejected` = all rejections
temporary; `Rejected` = any permanent rejection. All rejection reasons are user-visible strings
(interactive search shows them).

### 3.2 The specs that matter (with comic relevance)

Always-run (search + RSS), `DecisionEngine/Specifications/`:
- `QualityAllowedByProfileSpecification` — parsed quality allowed in profile. **Keep.**
- `UpgradeDiskSpecification` + `UpgradableSpecification` — is this actually better than the file
  on disk (profile order, revision, custom-format score, cutoff met)? **Keep — core.**
- `UpgradeAllowedSpecification` — profile forbids upgrades. **Keep.**
- `AcceptableSizeSpecification` / `MaximumSizeSpecification` — per-quality size bounds / global
  cap. **Keep (per-format MB bounds per issue).**
- `RetentionSpecification`, `MinimumAgeSpecification` (temporary) — usenet retention / min-age
  (let propagation finish before grabbing). **Keep both for SAB.**
- `ProtocolSpecification` — protocol enabled per delay profile. Keep if DDL is a second protocol.
- `ReleaseRestrictionsSpecification` — must-contain / must-not-contain terms. **Keep.**
- `QueueSpecification` — don't grab what's already downloading unless it's an upgrade. **Keep.**
- `BlocklistSpecification` — permanently skip blocklisted releases. **Keep — pairs with §4.6.**
- `BlockedIndexerSpecification` (temporary) — indexer in back-off. **Keep.**
- `AlreadyImportedSpecification` — don't re-grab a release already grabbed+imported. **Keep.**
- `RepackSpecification`, `ProperSpecification` (RSS) — proper/repack policy. Keep in reduced
  "fixed release" form.
- TV-shape only, drop for comics: `FullSeason`, `MultiSeason`, `SeasonPackOnly`, `SplitEpisode`,
  `SameEpisodes`, `SceneMapping`, `RawDisk`, `NotSample`, anime specs, `TorrentSeeding`.
- `FreeSpaceSpecification` (Disk priority) — enough disk before grabbing. **Keep.**

RSS-only (`Specifications/RssSync/` — each early-accepts when a search criteria is present):
- `MonitoredEpisodeSpecification` — series AND episode monitored. **Keep — core.**
- `HistorySpecification` — recent grab history already satisfies/cuts off. **Keep.**
- `DelaySpecification` (temporary) — see §3.4. **Keep.**
- `DeletedEpisodeFileSpecification`, `IndexerTagSpecification`, `PendingSpecification` — nice-to-have.

Search-only (`Specifications/Search/`): result actually matches the searched series/season/episode
(`SeriesSpecification`, `SeasonMatchSpecification`, `SingleEpisodeSearchMatchSpecification`,
`EpisodeRequestedSpecification`). **Keep** — with `q=`-only comic searching, wrong-series hits
are the norm, so "does this release map to the series/issue I asked for" is essential.

### 3.3 Prioritization

`DecisionEngine/DownloadDecisionPriorizationService.cs` groups accepted decisions per series and
orders with `DownloadDecisionComparer.cs` — first non-zero comparator wins, in order (verified
firsthand, lines 30–43):
1. quality (profile index; then revision if propers preferred)
2. custom-format score
3. protocol matches delay-profile preference
4. episode count (season pack preferred; more episodes wins)
5. lowest episode number
6. indexer priority
7. torrent peers (log-bucketed)
8. usenet age (bucketed freshness: <1 h ≫ <24 h ≫ <7 d)
9. size closeness to preferred size

**Comic version**: format rung → term/group score → indexer priority → age bucket → size
closeness. The bucketing trick (log/step buckets so tiny differences don't dominate) is worth
keeping.

### 3.4 Delay profiles

`Profiles/Delay/DelayProfile.cs`: per-tag profile with `UsenetDelay`/`TorrentDelay` (minutes),
`PreferredProtocol`, bypass flags (`BypassIfHighestQuality`,
`BypassIfAboveCustomFormatScore`). Assignment: best profile whose tags intersect the series
tags, ordered; profile 1 is the untagged catch-all (`DelayProfileService.BestForTags`).
`RssSync/DelaySpecification.cs`: skip for user searches; reject *temporarily*
(`MinimumAgeDelay`) while `release.AgeMinutes < delay`, with bypasses for highest-quality or
high-scoring releases. Purpose: wait for a better release before auto-grabbing the first thing
on RSS. **Keep in simplified single-protocol form** (one delay value + bypass-at-cutoff) —
valuable for comics where a low-quality scan often appears hours before the digital release.

### 3.5 Processing decisions / pending releases

`Download/ProcessDownloadDecisions.cs`: iterate prioritized qualified decisions; skip releases
covering an episode already grabbed this run; grab approved ones; **temporarily rejected →
pending queue** with reason Delay; download-client failures → pending with reason
DownloadClientUnavailable (and same-protocol releases stop attempting this run); further
releases for an already-handled episode stored as reason **Fallback**.
`Download/Pending/PendingReleaseService.cs` persists these; the delay spec consults the oldest
pending release age; pending items appear in the queue UI with "pending" status; fallback
releases are tried if the primary fails. Copy the three-reason pending model — it is how delay
profiles, client outages, and retry fallback all compose.

---

## 4. Download client abstraction (SABnzbd focus)

### 4.1 Abstraction

`Download/IDownloadClient.cs` / `DownloadClientBase.cs`: `Protocol`,
`Download(remoteEpisode) → downloadId` (client-side id, e.g. SAB `nzo_id`), `GetItems()` →
`DownloadClientItem`s, `RemoveItem(item, deleteData)`, `GetStatus()`, `MarkItemAsImported`.
`DownloadClientItem` (`Download/DownloadClientItem.cs`): `DownloadId`, `Category`, `Title`,
`TotalSize`/`RemainingSize`/`RemainingTime`, `OutputPath`, `Status`
(Queued/Paused/Downloading/Completed/Failed/Warning), `IsEncrypted`, `CanMoveFiles`,
`CanBeRemoved`. Multiple clients: `Download/DownloadClientProvider.cs` filters by protocol,
tags, blocked status, groups by priority and round-robins within the group;
`DownloadService` iterates candidates as a fallback chain. For foragerr, this interface is
exactly the seam for **SABnzbd + built-in DDL client** as two implementations of one protocol-ish
abstraction.

### 4.2 SABnzbd specifics

`Download/Clients/Sabnzbd/`:
- **Add**: `UsenetClientBase.Download` fetches the NZB bytes itself from the indexer (with
  retry), then `Sabnzbd.AddFromNzbFile` posts it with **`mode=addfile`** (never addurl),
  `cat=<TvCategory>` (default "tv"; foragerr: "comics"), and priority
  (`RecentTvPriority`/`OlderTvPriority`, `SabnzbdPriority` enum incl. Force/Paused). Returns
  first `nzo_id`; empty ⇒ rejected-release exception. Fetching the NZB yourself (rather than
  handing SAB the URL) keeps indexer auth server-side and lets you validate the NZB.
- **Proxy calls** (`SabnzbdProxy.cs`): `mode=addfile`, `mode=queue` (+`name=delete`),
  `mode=history` (+`name=delete&archive=`), `mode=version`, `mode=get_config`,
  `mode=fullstatus`, `mode=retry`; all `output=json&apikey=`.
- **GetItems**: queue + history concatenated, **filtered to the configured category**; queue
  sizes MB→bytes; `ENCRYPTED /` prefix → `IsEncrypted`; status mapping: paused→Paused,
  Queued/Grabbing/Propagating→Queued, else Downloading; history Failed→Failed
  (disk-full unpack message → Warning), Completed→Completed, Verifying/Extracting/Repairing→
  Downloading. History `Storage` path run through **remote path mapping**
  (`RemotePathMappings/`) — needed whenever SAB runs in a different container/host than foragerr.

### 4.3 Grab dispatch

`Download/DownloadService.cs DownloadReport`: pick client (or the explicitly requested one),
rate-limit grabs, call `client.Download(...)`, record indexer+client success/failure, then
publish `EpisodeGrabbedEvent` carrying `DownloadId`, client name/id.
`History/HistoryService.cs` handles it: one **Grabbed history row per episode** with
`DownloadId` and a data dict (indexer, guid, size, downloadUrl, publish date, protocol, score…).
**`DownloadId` is the join key for the entire rest of the pipeline.** A parallel
`Download/History/DownloadHistoryService.cs` keeps a per-download event log.

### 4.4 Queue tracking loop

- `RefreshMonitoredDownloadsCommand` scheduled **every 1 minute**, high priority
  (`Jobs/TaskManager.cs`, verified), plus debounce-triggered on grab/import events.
- `Download/TrackedDownloads/DownloadMonitoringService.cs Refresh()`: for each enabled client,
  `GetItems()`; each item → `TrackedDownloadService.TrackDownload` which **matches back to
  grabbed history by `DownloadId`**, re-parses the title, attaches the RemoteEpisode
  (series+episodes), and caches a `TrackedDownload` with
  `State ∈ {Downloading, ImportBlocked, ImportPending, Importing, Imported, FailedPending,
  Failed, Ignored}` and `Status ∈ {Ok, Warning, Error}` + status messages.
- Items in Downloading/ImportBlocked are checked by `FailedDownloadService.Check` then
  `CompletedDownloadService.Check`; then a `ProcessMonitoredDownloadsCommand` performs the
  state-advancing work (import / fail processing) — check (fast, per-refresh) and process
  (slow) are deliberately separate.
- The **Queue** shown in UI/API is built from tracked downloads (`Queue/QueueService.cs`
  rebuilds on `TrackedDownloadRefreshedEvent`, stable synthetic ids, publishes
  `QueueUpdatedEvent` → SignalR). Queue = live view of client state joined to library intent;
  nothing user-facing polls SAB directly.

### 4.5 Completed download handling (CDH)

`Download/CompletedDownloadService.cs`: when item Status==Completed and state Downloading:
validate output path (empty/foreign-OS path ⇒ warn "check remote path mapping"), resolve
series from parse or grab history, else **ImportBlocked** (publishes
`ManualInteractionRequiredEvent` — surfaces in UI for manual import). Good ⇒ **ImportPending**;
`DownloadProcessingService` then calls `Import`: state **Importing**, run the import pipeline
(§5) on the output path, then `VerifyImport` — all grabbed episodes imported ⇒ state
**Imported** + `DownloadCompletedEvent`; partial/rejected ⇒ back to ImportBlocked with messages.
After import, `Download/DownloadEventHub.cs` removes the item from SAB (delete + data) iff the
per-client `RemoveCompletedDownloads` flag is set. Copy this whole state machine; it is the
heart of "Sonarr-like" behavior.

### 4.6 Failed download handling + blocklist

- `Download/FailedDownloadService.cs`: item Failed or IsEncrypted (password-protected NZB) with
  matching grab history ⇒ **FailedPending** ⇒ processed to **Failed** + `DownloadFailedEvent`
  (carries series/episodes, source title, quality, grab data dict).
- `Blocklisting/BlocklistService.cs` handles the event: insert Blocklist row (series, episode
  ids, source title, indexer, size, publish date, protocol). **Match-back on future candidates**
  (`Blocklisted()`): usenet = same series + same title/size/publish-date/indexer
  ("SameNzb" comparison); torrent = info-hash or title. Backs the permanent
  `BlocklistSpecification` (§3.2).
- `Download/RedownloadFailedDownloadService.cs` (runs last on the event): if
  `AutoRedownloadFailed` config, immediately push a new search command for the affected
  episodes. Failed → blocklist → auto-search-again is the self-healing loop foragerr must have;
  it is what makes a bad/password-protected scan self-correct.

---

## 5. Import pipeline

### 5.1 Matching completed downloads to grabs

`MediaFiles/DownloadedEpisodesImportService.cs ProcessPath(outputPath, mode, series,
downloadClientItem)`: scan video files under the completed folder (skip `_UNPACK_`/`_FAILED_`,
samples, junk), resolve series from folder name if not already known from the tracked download,
then per-file decisions. The **download-client item title and the folder name are parsed as
additional evidence** alongside the file name.

`MediaFiles/EpisodeImport/ImportDecisionMaker.cs` builds a `LocalEpisode` per file and runs an
**aggregation pipeline** (`Aggregation/AggregationService.cs`) before the specs:
- `AggregateEpisodes`: choose the best ParsedInfo among file/folder/download-client-title.
- `AggregateQuality`: merge quality evidence by source order filename → folder → client item →
  mediainfo → release name, keeping highest confidence per component.
- `AggregateReleaseGroup`, `AggregateLanguage`, `AggregateReleaseInfo` (pulls the **grabbed
  release from history by DownloadId** so import can check "is this what we grabbed?").

**Comic version**: same three evidence sources (file name, folder name, grab record), a
much simpler aggregate (format from extension, tags/group from names, issue mapping), plus
comic-specific file validation — a cbz is a zip: verify archive opens and contains images
(the analogue of Sonarr's ffprobe/`HasAudioTrackSpecification`).

### 5.2 Import specifications (`MediaFiles/EpisodeImport/Specifications/`)

Accept/reject per file, same pattern as the decision engine. Worth keeping for comics:
- `UpgradeSpecification` — only import if better than the existing file (profile order,
  revision, score). **Core.**
- `AlreadyImportedSpecification` — same download id already imported.
- `FreeSpaceSpecification`, `NotUnpackingSpecification` (still being extracted/written).
- `MatchesGrabSpecification` — imported episodes must be in the grabbed release. **Keep** —
  guards against SAB folder cross-contamination.
- `MatchesFolderSpecification` — file consistent with its folder's parse.
- Drop/TV-only: samples, full-season, absolute-number, episode-title-required, audio-track
  (replace with archive-validity), split-episode.

### 5.3 Import execution

`MediaFiles/EpisodeImport/ImportApprovedEpisodes.cs`: order approved decisions by quality then
size; per file: build `EpisodeFile` record; **move vs copy**: explicit mode or Auto = move for
usenet, copy when the client says `CanMoveFiles == false` (seeding torrent) — with optional
hardlink-then-copy. `MediaFiles/UpgradeMediaFileService.cs`: on upgrade, the **old file goes to
the Recycle Bin** (`RecycleBinProvider`, permanent delete if unconfigured) before the new file
lands; DB row deleted with reason Upgrade. Destination path from the naming engine;
season/series folders auto-created (`EpisodeFileMovingService.cs`). Publishes
`EpisodeImportedEvent` (history row "Imported", download tracking advance, notifications).
Source folder deleted after move-mode import if only samples/junk remain (`ShouldDeleteFolder`).

### 5.4 Renaming / naming engine

`Organizer/FileNameBuilder.cs` + `NamingConfig.cs`:
- Config: `RenameEpisodes` (off ⇒ keep original filename), `ReplaceIllegalCharacters`,
  colon-replacement mode, per-type episode formats, `SeriesFolderFormat`,
  `SeasonFolderFormat`, `MultiEpisodeStyle`.
- Token system: `{Series Title}`, `{Series CleanTitle}`, `{season:00}`, `{episode:00}`,
  `{Episode Title}`, `{Quality Full}`, `{Release Group}`, `{MediaInfo …}`, id tokens — regex-driven,
  token **case controls output case**, custom separators/padding inside tokens, byte-aware
  truncation of the episode title to fit path limits, Windows reserved-name guards.
- Rename is previewable: `MediaFiles/RenameEpisodeFileService.cs` returns existing→new path
  diffs; execute moves files and publishes per-file renamed events.

**Comic naming tokens**: `{Series Title}`, `{Series CleanTitle}`, `{Volume Year}`,
`{issue:000}` (zero-pad, decimal-safe), `{Issue Title}`, `{Release Group}`, `{Format}`; folder
format `{Series Title} ({Year})`. Keep: token-case trick, preview-before-execute, illegal-char
policy, truncation.

### 5.5 File management / library scan

`MediaFiles/DiskScanService.cs`: per-series rescan (after refresh, after import errors, on
demand): enumerate media files under the series path, filter junk (extras folders, `@eadir`,
dotfiles), delete DB rows for vanished files (`MediaFileTableCleanupService`), then run
**unmapped files through the same ImportDecisionMaker** with `newDownload: false` — library
import and download import share one pipeline (major simplification worth copying).
`MediaFiles/MediaFileDeletionService.cs`: deletions go via Recycle Bin; empty-folder cleanup.
`RootFolders/RootFolderService.cs`: configured roots, unmapped-folder enumeration (feeds the
"import existing library" UI). Manual import
(`MediaFiles/EpisodeImport/Manual/ManualImportService.cs`): list candidate files with their
would-be decisions + rejections, let the user override series/episode/quality, then run the same
`ImportApprovedEpisodes` — this is the escape hatch for every mapping failure and the resolution
path for ImportBlocked downloads.

---

## 6. Eventing / messaging backbone → asyncio equivalent

### 6.1 Sonarr's model

- **Events** (`NzbDrone.Core/Messaging/Events/EventAggregator.cs`): `PublishEvent<T>`;
  handlers are any DI-registered class implementing `IHandle<T>` (synchronous, in-line,
  exceptions isolated per handler, optional ordering attribute) or `IHandleAsync<T>`
  (fire-and-forget thread-pool). Discovery is automatic via the container.
- **Commands** (`Messaging/Commands/`): every unit of background work is a `Command` object
  pushed to `CommandQueueManager` — persisted (survives restart; orphans re-queued on startup),
  **de-duplicated** (equal-bodied queued/started command returns the existing one),
  prioritized, with status Queued/Started/Completed/Failed and flags (exclusive, long-running,
  disk-access). `CommandExecutor` runs 3 worker threads pulling from the queue and dispatching
  to the single `IExecute<TCommand>` handler. Status changes publish `CommandUpdatedEvent` →
  debounced SignalR → the UI Activity/Tasks views.
- **Scheduler** (`Jobs/Scheduler.cs` + `TaskManager.cs`): a 30-second timer pushes any command
  whose `LastExecution + Interval` has passed. Built-in table (verified firsthand):
  RefreshMonitoredDownloads 1 min (High), MessagingCleanup 5 min, ImportListSync 5 min,
  UpdateSceneMapping 3 h, CheckHealth 6 h, UpdateCheck 6 h, RefreshSeries 12 h, Housekeeping
  24 h, CleanRecycleBin 24 h, Backup config-driven, **RssSync config-driven (default 15 min,
  min 10, 0=off)**. Executed scheduled commands update `LastExecution`.
- **UI push**: repository writes publish `ModelEvent<T>`; API controllers subscribed to them
  broadcast resource changes over SignalR (`Sonarr.Http/REST/RestControllerWithSignalR.cs`,
  `NzbDrone.SignalR/`).

### 6.2 Sensible asyncio-Python equivalent (brief)

- **Event bus**: a tiny in-process pub/sub — `bus.publish(EpisodeGrabbed(...))` with handlers
  registered by event dataclass type; run handlers sequentially in the publishing task with
  per-handler `try/except` (Sonarr's sync semantics), and offer `subscribe_async` that
  `asyncio.create_task`s fire-and-forget handlers. No broker needed.
- **Command queue**: an `asyncio.PriorityQueue` of pydantic command models + a `commands` table
  mirroring status; N worker tasks (2–3) `await queue.get()` and dispatch by type to a single
  registered executor coroutine. Dedup on push by (name, payload) among queued/started. On
  startup, mark orphaned started commands and re-queue queued ones. Long blocking work
  (archive extraction, hashing) goes to `asyncio.to_thread`.
- **Scheduler**: one loop task waking every 30 s, comparing `last_execution + interval` from a
  `scheduled_tasks` table, pushing due commands with trigger=scheduled. (Or APScheduler, but the
  hand-rolled loop matches Sonarr and stays inspectable.)
- **UI push**: FastAPI WebSocket endpoint replacing SignalR; broadcast
  `{name: "queue", action: "updated", resource: {...}}` messages debounced ~100 ms; frontend
  React Query invalidates/patches caches per message (exactly Sonarr's current frontend, §7.4).

---

## 7. API v3 + UI structure (high level)

### 7.1 Resource inventory (`Sonarr.Api.V3/`, route prefix `api/v3/`)

Series (+lookup, editor/bulk, import), Episode (get/monitor toggle), EpisodeFile, Queue
(paged + details + status + actions: grab/remove), Release + ReleasePush, Command, History
(paged), Blocklist (paged), Wanted/Missing + Wanted/Cutoff (paged), Calendar (+iCal feed),
ManualImport, Profiles (quality/delay/release), CustomFormats, Indexer, DownloadClient,
Notification, ImportList (all provider-style), Config/{host, mediamanagement, **naming**, ui,
downloadclient, indexer}, RootFolder, System/Status, System/Tasks, Health, Tags, Parse (debug
endpoint: paste a title, see the parse), FileSystem, Logs, Update.

### 7.2 Conventions worth imitating

- `RestController<TResource>` CRUD base + FluentValidation per-verb validators
  (`Sonarr.Http/REST/RestController.cs`); resources carry `id`; PUT id from route.
- **Paging envelope** (`Sonarr.Http/PagingResource.cs`):
  `{page, pageSize, sortKey, sortDirection, totalRecords, records[]}` with whitelisted sort keys
  — used by queue/history/blocklist/wanted.
- **Provider schema pattern** (`Sonarr.Api.V3/ProviderControllerBase.cs`,
  `Sonarr.Http/ClientSchema/SchemaBuilder.cs`): `GET /indexer/schema` returns implementation
  templates each with `fields[]` (name, label, type, options, advanced) generated from the
  settings class; `POST /indexer/test` and `/testall`; the UI settings forms are 100% driven by
  this. This is how foragerr adds DogNZB vs NZB.su vs future DDL sources without new frontend code.
- **Command endpoint**: `POST /command {name: "RefreshSeries", seriesIds:[...]}` → 201 with
  trackable `CommandResource` (status/queued/started/duration); `GET /command` lists running;
  progress via WebSocket. Every button in the UI that "does work" goes through this.
- **Auth**: `X-Api-Key` header or `apikey` query (`Sonarr.Http/Authentication/`).
- **Release endpoint semantics** (`Sonarr.Api.V3/Indexers/ReleaseController.cs`):
  `GET /release?episodeId=` runs a *live* interactive search and returns every decision with
  `approved/temporarilyRejected/rejected` + `rejections[]`; each is cached 30 min keyed
  `{indexerId}_{guid}`; `POST /release {guid, indexerId}` grabs from that cache (404 if
  expired → "search again"). Copy this exactly for the interactive-search UX.

### 7.3 Resource shapes worth copying (trimmed to comic fields)

- **SeriesResource**: title, sortTitle, status, overview, images, year, path, qualityProfileId,
  monitored, monitorNewItems, external ids, tags, added, statistics (issueFileCount/issueCount/
  sizeOnDisk — Sonarr computes these via a stats aggregation query, `SeriesStats/`),
  addOptions (write-only), remotePoster (lookup results).
- **EpisodeResource→IssueResource**: seriesId, issueNumber, title, coverDate, monitored,
  hasFile, issueFileId, nested issueFile, lastSearchTime.
- **ReleaseResource**: guid, indexerId/indexer, title, size, age/ageHours, quality(format),
  approved/temporarilyRejected/rejected, rejections[], downloadAllowed, releaseWeight, score.
- **QueueResource**: seriesId/issueId, nested series/issue, title, size/sizeleft, status,
  trackedDownloadStatus (ok/warning/error), trackedDownloadState, statusMessages[], downloadId,
  downloadClient, indexer, outputPath, estimatedCompletionTime.
- **HistoryResource**: eventType (grabbed/downloadFolderImported/downloadFailed/deleted/renamed),
  sourceTitle, quality, date, downloadId, data{} (free-form per-event dict), nested series/issue.

### 7.4 Frontend (`frontend/src/`)

Pages mirror API resources 1:1: Series (index/details), AddSeries (lookup + library import),
Activity/{Queue, History, Blocklist}, Wanted/{Missing, CutoffUnmet}, Calendar,
Settings/{MediaManagement, Profiles, Quality, Indexers, DownloadClients, …}, System/{Status,
Tasks, Logs}, InteractiveSearch and InteractiveImport overlays. Modern stack (relevant since
foragerr is React+TS): **React Query for all server state** (query keys mirror API paths),
zustand for local UI state, one `SignalRListener` component mapping resource-change WebSocket
messages onto React Query cache invalidations/patches (`frontend/src/Components/SignalRListener.tsx`).
That exact trio (react-query + small client-state store + WS-driven invalidation) is the
recommended foragerr frontend architecture.

---

## 8. Candidate requirements for foragerr (plain prose, no IDs)

Grouped; **bold** = the Sonarr behaviors that matter most for a comic-shaped domain.

**Library / domain**
- A comic series is added from ComicVine by volume id; the add flow fetches metadata, applies
  user choices (root folder, quality/format profile, monitoring strategy), validates the path,
  and then triggers refresh → scan → optional missing-issue search as a chained sequence.
- **Issues are reconciled against ComicVine on every refresh**: new issues inserted (monitored
  per the series' new-item policy), changed issues updated, issues no longer present removed.
  Scheduled refresh (~12 h) with per-series staleness/skip rules; ended series refresh rarely.
- **Two-level monitored flags** (series + issue) as the single gate for automatic grabbing;
  add-time monitoring strategies (all / future / missing / existing / none); wanted = monitored
  + published + no file, derived not stored.
- Quality reduced to a short ordered **format profile** (e.g. cbz > cbr > pdf) with a cutoff and
  an upgrade-allowed flag, plus a small revision counter for "fixed" re-releases, plus scored
  preferred/avoided terms and release groups (Sonarr's custom formats — likely more useful for
  comics than the quality ladder itself). Per-format size sanity bounds per issue.

**Indexers / search**
- Indexers are configuration rows (implementation + JSON settings) validated by a live test;
  each has independent toggles for RSS, automatic search, and interactive search, a priority,
  and Newznab categories (comics: 7030).
- Newznab support probes `t=caps`, pages with offset/limit, and — since comic ids don't exist in
  Newznab — searches primarily by **cleaned-title `q=` query within the comics category**, with
  the tiered request-generator shape kept so smarter query forms can be added.
- **Three search paths, one decision engine**: scheduled RSS sync (config interval, default
  ~15 min) over all RSS-enabled indexers; automatic searches triggered by commands (post-add,
  post-failure, wanted); interactive search that returns every candidate with its rejection
  reasons for manual grabbing (results cached briefly so a subsequent grab request needs no
  re-search).
- Release titles are parsed by a pure function into (series title, issue number, year, format,
  tags, group) and mapped to library series/issues via clean titles and user-editable aliases;
  unmappable releases become visible rejection reasons, never crashes.
- **Per-indexer failure back-off** with an escalating disable ladder and automatic recovery;
  disabled indexers are skipped by RSS and search and shown in health.

**Decisions**
- Candidate releases pass through an ordered list of accept/reject specifications, each producing
  a user-visible reason; rejections are **permanent or temporary**; a fully-temporarily-rejected
  release goes to a pending queue instead of being dropped.
- Specifications must cover at least: profile-allowed format, genuinely-an-upgrade over disk
  (with cutoff), already imported, already in queue, blocklisted, indexer disabled, size bounds,
  usenet retention and minimum age, must/must-not-contain terms, monitored-only for RSS,
  matches-the-searched-issue for searches, free disk space.
- Among accepted candidates, pick the best by ordered comparators (format rung, term/group score,
  indexer priority, bucketed age, size closeness to preferred).
- **A delay profile** can hold RSS-sourced grabs in pending for N minutes (bypass at cutoff
  quality), so an early low-grade scan doesn't beat the digital release; user-invoked searches
  bypass delay.

**Downloading (SABnzbd + DDL)**
- Download clients implement one small interface (download → client id, list items, remove item,
  status); SAB support adds NZBs by uploading the fetched file (`mode=addfile`) with a dedicated
  category, and reads queue+history filtered to that category, mapping SAB statuses onto a common
  item status; remote path mapping translates SAB's completed paths when it runs elsewhere.
  The built-in DDL client implements the same interface.
- Every grab writes a history record whose **download id is the join key**; a ~1-minute tracking
  loop lists client items, matches them to grab history by that id, and maintains a per-download
  state machine (downloading → import pending → importing → imported; or failed pending →
  failed; or import blocked awaiting manual action) that backs the visible queue.
- **Completed downloads import automatically**; unresolvable ones become "manual interaction
  required" rather than silently failing; imported items are removed from SAB only if the
  per-client remove flag says so.
- **Failed or password-protected downloads are blocklisted (matched by title/size/date/indexer)
  and automatically re-searched** — the self-healing loop.

**Import / files**
- Completed-download import and library rescan share one import pipeline: parse evidence from
  file name, folder name, and the grab record; run import specifications (upgrade check, matches
  the grab, not still unpacking, free space, valid readable archive containing images); import
  approved files.
- Import moves (usenet) with per-issue records; **upgrades send the replaced file to a recycle
  bin** before the new file lands.
- Renaming is template-driven with tokens (series title, year, zero-padded decimal-safe issue
  number, issue title, format, group), previewable before execution, with illegal-character and
  path-length handling; renaming can be disabled to keep original names.
- Manual import lists candidate files with their would-be decisions and lets the user override
  series/issue/format before importing — the resolution path for every mapping failure.

**Backbone / API / UI**
- In-process event bus (typed events, isolated handlers) + persisted, de-duplicated,
  prioritized **command queue** with a few async workers; every background action is a command
  with visible status; a 30-second scheduler pushes interval-due commands (tracking loop ~1 min,
  RSS per config, refresh ~12 h, housekeeping daily).
- REST API mirroring Sonarr v3 shapes: paged envelopes for queue/history/blocklist/wanted,
  provider schema endpoints driving dynamic settings forms, `POST /command` for actions,
  release endpoint returning decisions-with-rejections, API-key auth.
- WebSocket resource-change broadcasting; frontend of React Query + small client store + one
  WS listener invalidating caches; pages: Series, Add, Queue/History/Blocklist, Wanted,
  Settings, System — plus foragerr's OPDS endpoint, which is simply a read-only projection of
  series/issue-file resources and needs nothing from Sonarr.

### Top behaviors ranked for a comic-shaped domain

1. **Monitored-flag lifecycle + metadata-refresh reconciliation** (§1) — defines what the app wants.
2. **Grab → track-by-download-id → completed-download-handling state machine** (§4) — defines
   how wants become files without babysitting.
3. **Decision specifications with visible permanent/temporary rejections** (§3) — makes every
   automatic choice explainable and powers interactive search.
4. **Failed-download blocklist + auto re-search** (§4.6) — self-healing against bad scans.
5. **Single shared import pipeline + previewable template renaming** (§5).
6. **Command queue + scheduler + WS push** (§6) — the chassis everything above runs on.
7. Provider schema pattern + release-cache grab API (§7) — cheap extensibility and the right UX.
