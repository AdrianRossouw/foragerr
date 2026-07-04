# Baseline Exclusions (draft — folded into proposal Non-goals)

## IDX — Exclusion: "experimental" nzbindex scraper  _(from acquisition.md)_

- Shall: The baseline SHALL NOT implement Mylar's "Experimental" provider (nzbindex.nl RSS scrape with zero-pad OR-queries).
- Acceptance: No nzbindex-specific code or configuration exists; the capability is recorded as excluded in the registry.
- Source: mylar-fs IDX ("Experimental" provider); mylar-fs SRCH (RSS pipeline)
- Milestone: B
- Notes: Recommend permanent exclusion: unauthenticated scrape of a raw index yields obfuscated/unverified posts, high junk ratio, no API contract, and duplicates what two paid Newznab indexers already provide. Revisit only if DogNZB/NZB.su both die.

## DL — Exclusion: NZBGet client  _(from acquisition.md)_

- Shall: The baseline SHALL NOT implement an NZBGet download client.
- Acceptance: SABnzbd is the only usenet client implementation; the exclusion is recorded in the registry.
- Source: mylar-fs DL (NZBGet XML-RPC); sonarr-arch §4 (client abstraction)
- Milestone: B
- Notes: Recommend backlog, not permanent exclusion: the deployment target runs SABnzbd; NZBGet (and its Usenet-facing fork landscape) adds a second protocol dialect and history-verification quirks for zero user value today. The client abstraction keeps the door open cheaply.

## DL — Exclusion: blackhole and external completion scripts  _(from acquisition.md)_

- Shall: The baseline SHALL NOT implement a blackhole (.nzb drop directory) client nor external client-side completion scripts (ComicRN-style) posting back to the API.
- Acceptance: No blackhole client or forceProcess-style script entry point exists; exclusion recorded.
- Source: mylar-fs DL (blackhole), mylar-fs PP (intake path 1, double-PP detection)
- Milestone: B
- Notes: Recommend permanent exclusion. Blackhole loses the download id join key (forces name-matching import); external scripts create the double-processing hazard Mylar needs special detection for. Built-in CDH polling supersedes both.

## DDL — Exclusion: external mega-backed download server  _(from acquisition.md)_

- Shall: The baseline SHALL NOT implement Mylar's "DDL(External)" provider (externally hosted mega-backed download server).
- Acceptance: No external-server provider exists; exclusion recorded in the registry.
- Source: mylar-ddl §1.1 (ENABLE_GETCOMICS vs external provider); mylar-fs DDL
- Milestone: B
- Notes: Recommend permanent exclusion: it is an opaque third-party relay with unclear operation, trust, and provenance — exactly the kind of surface FRG-PROC-006 exists to keep out. GetComics + mirror adapters cover the need.

## TOR — Exclusion: 32P private tracker  _(from acquisition.md)_

- Shall: The system SHALL NOT implement direct 32Pages private-tracker integration (session login, cookie persistence, Cloudflare scraping, inkdrops, notification feeds, authenticated downloads).
- Acceptance: No 32P-specific code, configuration, or credentials surface exists; exclusion recorded.
- Source: mylar-fs TOR (32P feature list)
- Milestone: B
- Notes: Recommend permanent exclusion: scrape-based authenticated automation against a private tracker is brittle (Mylar needs auto-disable to avoid bans), carries account-loss risk, stores credentialed sessions, and is a large bespoke surface for one site of uncertain longevity. If private-tracker access is ever wanted, it arrives as a Torznab endpoint via Prowlarr/Jackett — zero foragerr code.

## TOR — Exclusion: built-in public-tracker scrapers  _(from acquisition.md)_

- Shall: The system SHALL NOT implement site-specific public-tracker scrapers (WorldWideTorrents scrape, Demonoid RSS, or successors).
- Acceptance: Torrent search reaches trackers only through Torznab indexers; exclusion recorded.
- Source: mylar-fs TOR (WWT/Demonoid, dead TPSE code)
- Milestone: B
- Notes: Recommend permanent exclusion: per-site scrapers rot (Mylar already carries dead tracker code), and Torznab proxies exist precisely to absorb that churn outside the application.

## TOR — Exclusion: seedbox harvesting and watch-dir clients  _(from acquisition.md)_

- Shall: The system SHALL NOT implement seedbox SFTP harvesting (auto-snatch completion monitor + lftp/sftp fetch scripts) nor watch-directory/SFTP-upload torrent clients.
- Acceptance: The only torrent handoff is the API-based client (qBittorrent); exclusion recorded.
- Source: mylar-fs TOR (watchdir/SFTP, AUTO_SNATCH_SCRIPT, getlftp.sh)
- Milestone: B
- Notes: Recommend permanent exclusion: shell-script harvesters with SSH credentials are a large STRIDE surface (remote command execution, credential storage) serving a deployment (remote seedbox) explicitly outside foragerr's single-home-server target. Watch-dir clients lose the download-id join key, degrading tracking to name matching.


---

# Additional recorded exclusions (from completeness-critic audit)

These were implicitly dropped by the drafting pass; recorded here so a future change can
cite the decision rather than treat them as gaps.

## One-off issue downloads _(SER/SRCH)_
- Grabbing an issue without watching its series (Mylar `oneoffhistory`, "weekly one-off
  downloads"): **excluded**. FRG-SRCH-003 rejects releases for untracked series ("unknown
  series"). Rationale: the derived-wanted model (FRG-SER-004) has no home for issues outside
  a monitored series; the substitute is "add the series with monitor-none, monitor the one
  issue." Review trigger: user demand for true series-less grabs.

## Legacy metadata scrapers _(META)_
- GCD, ComicBookDB, publisher solicitations: **excluded**. ComicVine (FRG-META-*) is the sole
  metadata source. Rationale: single well-supported source over three rotting HTML scrapers.

## READ area — reader / device sync / reading lists
- In-browser reader, tablet SFTP sync, read/unread reading lists: **permanently out of scope**
  (CLAUDE.md). foragerr reads via OPDS clients only (FRG-OPDS-*). Recorded so a future reader
  proposal must reopen the decision explicitly.
