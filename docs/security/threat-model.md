# foragerr — System-wide STRIDE Threat Model (FRG-PROC-006)

Read-only security analysis staged outside the repo per FRG-PROC-008. Feeds the requirements
baseline. Sources: `docs/research/mylar-{opds,ddl,comicvine,filename-parsing,feature-surface}.md`
and the scratchpad drafts `baseline/{library-domain,acquisition,files-domain,interfaces,platform}.md`.

## System context and global trust boundaries

- **Deployment**: single Docker container (linuxserver.io conventions) on a home server;
  Python/FastAPI + SQLite + React. All persistent state under `/config`.
- **Network posture**: reachable only over Tailscale. **M1 ships with NO application auth** — a
  deliberate, owner-accepted risk whose sole compensating control is the tailnet boundary
  (RISK-020). Auth (session/API-key/OPDS-Basic) lands M3.
- **Users**: single trusted operator + iPad OPDS reader apps (also on the tailnet).
- **Untrusted inputs crossing a trust boundary**:
  1. Comic archives (CBZ/CBR/CB7/PDF) from the internet (usenet, DDL, existing library).
  2. Scraped GetComics HTML + files from Mega/MediaFire/Pixeldrain/main host.
  3. ComicVine responses (user-editable wiki → attacker-influenced text + image URLs).
  4. Newznab/Torznab indexer responses (untrusted XML/RSS).
  5. External weekly-pull JSON source.
  6. Release titles, filenames, redirect URLs.
  7. CBL reading-list files (untrusted XML).
  8. Client-supplied HTTP/OPDS/WS request parameters.
- **Primary trust boundary**: the FastAPI listener (LAN/tailnet → process). Secondary: every
  outbound integration (process → third-party) and the filesystem (process → `/config`, `/comics`,
  `/downloads` volumes).

Legend for coverage: draft file `library-domain`=LD, `acquisition`=ACQ, `files-domain`=FD,
`interfaces`=IF, `platform`=PF. Requirements cited by their `### AREA — <name>` heading (no IDs
allocated yet).

---

## COMP 1 — Web API / UI (FastAPI + React)

- **Assets**: entire library/config/queue state; the operator's browser session; all control
  operations.
- **Trust boundary**: tailnet client → listener. No auth in M1/M2.
- **Threats**
  - **T-API-1 (Spoofing/Elevation)**: unauthenticated access to all control endpoints in M1/M2.
    Coverage: PF `AUTH — M1/M2 no-auth accepted risk` (canonical owner of the accept), PF
    `DEP — Tailscale-scoped exposure` (compensating control), PF `AUTH — single-user web login`
    + `AUTH — uniform coverage of all surfaces` (M3 fix). RISK-020.
  - **T-API-2 (Tampering/SQLi)**: injection through client-influenced query values into DB.
    Coverage: IF `OPDS — Parameterized queries throughout` (stated app-wide in spirit); PF
    `DB — typed, sentinel-free schema`; IF `API — Paging envelope` (whitelisted sort keys as
    ORDER-BY defense). RISK-002.
  - **T-API-3 (Tampering/XSS)**: attacker-influenced strings (CV wiki fields, scraped DDL text,
    release titles) rendered in the React UI. Coverage: LD `META — ComicVine content is untrusted
    input`, PF `NFR — untrusted external content handling`. RISK-011, RISK-014.
  - **T-API-4 (Repudiation)**: no auth audit trail before M3; state changes unattributable.
    Coverage: PF `AUTH — login rate limiting and audit`, PF `SCHED — persisted job history`
    (command audit). Gap: no security-event audit before M3 (accepted with RISK-020).
  - **T-API-5 (DoS)**: unbounded request bodies / expensive endpoints; no request-size or
    rate limit on the listener. Coverage: PF `NFR — UI responsiveness at library scale`
    (pagination, no unbounded arrays). **Gap G-1**: no explicit request-body-size cap / listener
    rate limit → FRG-NFR-014 (listener request resource limits). RISK-021.
  - **T-API-6 (Elevation/CSRF)**: state-changing endpoints reachable via forged cross-site
    requests once cookie-session auth exists. Coverage: PF `AUTH — session management` (SameSite,
    HttpOnly). **Gap G-5**: CSRF posture not consolidated; API-key header requests are
    CSRF-immune but the session UI needs an explicit stance → SEC-new `CSRF & WebSocket-origin`.
    RISK-022.

---

## COMP 2 — WebSocket resource-change channel

- **Assets**: live view of library/queue/command state.
- **Trust boundary**: browser → WS endpoint (same listener).
- **Threats**
  - **T-WS-1 (Information disclosure)**: unauthenticated subscription leaks all resource changes.
    Coverage: IF `API — WebSocket resource-change push` (Notes: WS auth is AUTH/M3); PF
    `AUTH — uniform coverage of all surfaces` (explicitly names WebSocket). RISK-020.
  - **T-WS-2 (Spoofing/CSWSH)**: cross-site WebSocket hijacking — a malicious page in the
    operator's browser opens a WS to the tailnet host and reads pushed data, bypassing cookie
    SameSite if origin is unchecked. **Gap G-5**: no Origin validation requirement on the WS
    handshake → SEC-new `CSRF & WebSocket-origin`. RISK-022.
  - **T-WS-3 (DoS)**: many idle sockets / flooding. Coverage: IF `API — WebSocket…` debounce.
    Low residual. RISK-021 (shared).

---

## COMP 3 — OPDS catalog server

- **Assets**: comic files on disk; library metadata; iPad reader access.
- **Trust boundary**: OPDS reader app (tailnet) → listener; server → filesystem.
- **Threats**
  - **T-OPDS-1 (Information disclosure — headline)**: arbitrary file read via client-supplied
    path (Mylar `deliverFile` traversal). Coverage: IF `OPDS — Library-id-based file resolution
    only (no client-supplied paths)` (security-by-construction). RISK-001.
  - **T-OPDS-2 (Tampering/SQLi)**: id/arc params interpolated into SQL (Mylar S3). Coverage:
    IF `OPDS — Parameterized queries throughout`. RISK-002.
  - **T-OPDS-3 (Spoofing/Elevation)**: OPDS world-readable, exempt from site auth (Mylar S2).
    Coverage: PF `AUTH — HTTP Basic for OPDS realm`, PF `AUTH — uniform coverage of all surfaces`
    (fixed exempt list); until M3, RISK-020. RISK-003.
  - **T-OPDS-4 (Spoofing/MITM — weak auth primitives, Mylar S4)**: plaintext Basic, no TLS
    enforced, no lockout. Coverage: PF `AUTH — password storage with modern KDF` (Basic verifies
    against KDF hash), PF `AUTH — login rate limiting and audit`; TLS via Tailscale (PF
    `DEP — Tailscale-scoped exposure`). RISK-004.
  - **T-OPDS-5 (DoS — zip-bomb / decompression, Mylar S5)**: server-side archive open + PIL
    resize (`LOAD_TRUNCATED_IMAGES`) on untrusted files at feed/stream time. Coverage: IF
    `OPDS — Resource limits on archive and image handling`, IF `OPDS — Cached page counts and
    page index` (no open-every-archive), IF `OPDS — Acquisition feeds…` (no archive I/O at feed
    time). RISK-005.
  - **T-OPDS-6 (Information disclosure — egress)**: hotlinked ComicVine cover URLs leak iPad
    client requests to a third-party CDN. Coverage: IF `OPDS — Cover and thumbnail links with
    local fallback` (served locally). RISK-023.

---

## COMP 4 — Indexer clients (Newznab / Torznab)

- **Assets**: indexer API keys; search integrity; the process (via XML parsing).
- **Trust boundary**: process → indexer host (config-supplied URL); indexer response → parser.
- **Threats**
  - **T-IDX-1 (Information disclosure)**: API keys in query strings leaking to logs. Coverage:
    PF `NFR — secret redaction in logs and errors`; ACQ `IDX — Newznab response parsing…` (typed
    errors). RISK-013 (key-in-URL class).
  - **T-IDX-2 (DoS/Tampering — XXE)**: Newznab/Torznab responses are **untrusted XML/RSS** parsed
    server-side; entity-expansion / external-entity attacks (billion-laughs, XXE) from a
    malicious or compromised indexer. Coverage: none in ACQ `IDX — Newznab response parsing and
    error mapping` (no XXE hardening stated). **Gap G-2** → SEC-new `Hardened XML parsing`.
    RISK-024.
  - **T-IDX-3 (SSRF via config)**: an indexer/Torznab base URL pointed at an internal/loopback
    address turns the server into a fetch proxy. Coverage: PF `NFR — bounded, verified outbound
    requests` (timeouts/redirect caps only). **Gap G-3** → SEC-new `SSRF egress controls`.
    RISK-025.
  - **T-IDX-4 (Spoofing/Tampering — content authenticity)**: indexer returns a mislabelled
    payload (HTML/error page where an NZB is expected). Coverage: ACQ `DL — SABnzbd add via file
    upload` (fetch + validate NZB bytes before handoff), ACQ `IDX — Newznab response parsing…`.
    RISK-026.
  - **T-IDX-5 (DoS — availability)**: hostile/slow indexer wedges workers. Coverage: PF
    `NFR — bounded, verified outbound requests`, ACQ `IDX — Indexer failure back-off and
    recovery`, PF `NFR — indexer and DDL politeness with failure backoff`. RISK-027.

---

## COMP 5 — SABnzbd client

- **Assets**: SAB credentials/URL; downloaded content paths.
- **Trust boundary**: process → SAB host (config URL); SAB-reported paths → import.
- **Threats**
  - **T-SAB-1 (Elevation — reduced attack surface, by design)**: Mylar's add-by-URL made SAB
    pull the NZB from Mylar's own API with a one-time key (extra callback auth surface). Coverage:
    ACQ `DL — SABnzbd add via file upload` (deliberate exclusion of add-by-URL) + ACQ
    FRG-DL-003 (server-side upload) + FRG-DL-009 (CDH-only intake). RISK-028.
  - **T-SAB-2 (Tampering — path)**: SAB reports a completed path the process then reads/moves;
    remote/foreign path confusion. Coverage: ACQ `DL — Remote path mapping`, FD `PP — Remote path
    mapping`. Residual: attacker-controlled path *content* handled by import validation. RISK-029.
  - **T-SAB-3 (Information disclosure)**: SAB API key at rest / in logs. Coverage: PF
    `AUTH — at-rest secret encryption`, PF `NFR — secret redaction in logs and errors`. RISK-013.
  - **T-SAB-4 (SSRF via config)**: SAB host URL pointed internally. Coverage: **Gap G-3** →
    SEC-new `SSRF egress controls`. RISK-025 (shared).

---

## COMP 6 — DDL scraper + downloader (GetComics + mirror hosts)

- **Assets**: Cloudflare clearance cookies; the process; the download directory; the library.
- **Trust boundary**: process → getcomics.org + arbitrary scraped hosts; scraped HTML/redirect
  URLs/files → filesystem + parser.
- **Threats**
  - **T-DDL-1 (Tampering/Path traversal)**: download filename derived from redirect-final URL
    (`unquote` before `basename`; attacker-controlled). Coverage: ACQ `DDL — Safe filename
    generation`. RISK-006.
  - **T-DDL-2 (SSRF / Information disclosure)**: scraped hrefs fetched with the session cookie,
    redirects followed blindly; `run.php`/`go.php` URL mutation. Coverage: ACQ `DDL — Outbound
    URL security` (per-provider scheme/host allowlist, redirect cap re-validated, no cross-host
    cookies), PF `NFR — bounded, verified outbound requests`. RISK-007.
  - **T-DDL-3 (DoS/Tampering — zip extraction)**: `zipfile.extractall` on hostile packs
    (zip-bombs, `../` entries, symlinks), pre-verification. Coverage: ACQ `DDL — Safe archive
    extraction` (caps, traversal/symlink rejection, staging dir; B, tied to packs). RISK-008.
  - **T-DDL-4 (MITM / Credential exposure)**: FlareSolverr call uses `verify=False`; clearance
    cookies persisted plaintext at `.gc_cookies.dat`; solver URL an SSRF pivot. Coverage: ACQ
    `DDL — Cloudflare session handling` (TLS-verified, 0600 cookies treated as credential, not
    logged/exported), ACQ `DDL — Outbound URL security` (no `verify=False` anywhere). RISK-009.
  - **T-DDL-5 (Tampering — content authenticity)**: single hardcoded upstream (getcomics.org)
    → domain takeover becomes a malware channel; CRC does not authenticate content. Coverage:
    ACQ `DDL — Content verification before import` (magic-number + archive integrity + size),
    FD `PP — Archive validity verification` (structural: cbz opens + contains images). Residual
    supply-chain trust accepted (RISK-015).
  - **T-DDL-6 (XSS / Log injection)**: scraped series titles/sizes/years flow into logs, DB, UI.
    Coverage: PF `NFR — untrusted external content handling`, LD `META — …untrusted input`.
    Residual log-injection (CR/LF forging) — see G-1 note. RISK-014.
  - **T-DDL-7 (Repudiation / ToS)**: spoofed UA + Cloudflare evasion are ToS-sensitive.
    Coverage: ACQ `DDL — Cloudflare session handling` Notes (conscious registry-recorded
    decision). RISK-016.
  - **T-DDL-8 (DoS)**: unbounded pagination walk; no jitter/429 backoff. Coverage: ACQ
    `DDL — Politeness and provider self-protection`, PF `NFR — indexer and DDL politeness with
    failure backoff`. RISK-027 (shared).
  - **T-DDL-9 (Tampering — split-tunnel proxy surprise)**: Mylar proxy applied only to this
    session. Coverage: ACQ `DDL — Outbound URL security` Notes (proxy, if added, process-wide).
    RISK-017 (accepted/excluded).

---

## COMP 7 — Archive / CBZ handling (import verify, page-count, cover extraction, tagging)

- **Assets**: the process (memory/CPU); the library; `/config` cover cache.
- **Trust boundary**: untrusted archive bytes → zip/rar/PIL; archive member names → filesystem
  (cover cache write, ComicInfo rewrite).
- **Threats**
  - **T-ARCH-1 (DoS — decompression bomb)**: import-time archive validity check and cover
    extraction open untrusted archives; no entry/size caps stated for the *import* or
    *cover-extraction* paths (OPDS path is covered separately). Coverage: FD `PP — Archive
    validity verification` (opens + image-present only, no bomb caps); OPDS limits are OPDS-only.
    **Gap G-4** → SEC-new `Archive-processing safety (cross-cutting)`. RISK-010.
  - **T-ARCH-2 (Tampering — Zip-Slip on write)**: cover extraction writing a member by its
    in-archive name, and in-process ComicInfo.xml rewrite, can be steered by hostile member
    names/paths. Coverage: DDL extraction covers DDL packs only; import/cover/tagging not
    covered. **Gap G-4** → SEC-new `Archive-processing safety (cross-cutting)`. RISK-010.
  - **T-ARCH-3 (DoS — truncated/malformed image)**: PIL `LOAD_TRUNCATED_IMAGES` + resize on
    hostile images (covers, PSE). Coverage: IF `OPDS — Resource limits on archive and image
    handling` (OPDS); pixel-dimension caps for cover extraction at import not stated → folds into
    G-4. RISK-005 (shared).
  - **T-ARCH-4 (Tampering — password-protected/corrupt archives)**: Coverage: FD `PP — Archive
    validity verification` (invalid → failed path), ACQ `DL — Failed download handling`. RISK-030.

---

## COMP 8 — ComicVine client

- **Assets**: CV API key; series/issue metadata integrity; the process (XML/timeouts).
- **Trust boundary**: process → comicvine.gamespot.com; CV response (wiki content + image URLs)
  → DB/UI/search/image-fetch.
- **Threats**
  - **T-CV-1 (Information disclosure — key-in-URL)**: API key in every query string → logs/proxy
    leak. Coverage: LD `META — API key handling` (param + scrubbed), PF `NFR — secret redaction
    in logs and errors`. RISK-013.
  - **T-CV-2 (Tampering/MITM — TLS off)**: `CV_VERIFY` disables cert verification globally.
    Coverage: LD `META — ComicVine client fundamentals` (TLS on, no global off-knob), PF
    `NFR — bounded, verified outbound requests`. RISK-012.
  - **T-CV-3 (Injection/Steering)**: user-editable wiki HTML flows into names/aliases/descriptions
    → XSS in UI and *steers* downstream indexer/DDL search queries. Coverage: LD `META —
    ComicVine content is untrusted input`, PF `NFR — untrusted external content handling`.
    RISK-011.
  - **T-CV-4 (DoS — no bounds)**: `requests.get` without timeout; XML minidom/expat entity
    expansion. Coverage: LD `META — ComicVine client fundamentals` (JSON not XML — sidesteps
    expat), PF `NFR — bounded, verified outbound requests`. Residual XXE only if any XML path
    remains → G-2. RISK-024 (shared).
  - **T-CV-5 (SSRF — cover image fetch)**: CV `image`/`ImageURL` fields are wiki-editable and the
    server fetches them into the cover cache; a crafted URL targets internal/loopback services.
    Coverage: LD `META — Cover art download and cache` (no allowlist/SSRF control); DDL allowlist
    does not apply here. **Gap G-3** → SEC-new `SSRF egress controls`. RISK-025.
  - **T-CV-6 (Repudiation/ToS — spoofed UA)**: Coverage: LD `META — ComicVine client
    fundamentals` (honest configurable UA — diverges from Mylar). Low residual.

---

## COMP 9 — Filename parser / renamer / file mover

- **Assets**: parsing robustness; library filesystem layout; `/comics` volume.
- **Trust boundary**: untrusted filenames/titles → parser; parsed + CV-derived fields →
  destination paths.
- **Threats**
  - **T-FILE-1 (DoS — parser crash)**: Mylar wraps whole passes in bare `except`; hostile
    filenames could crash. Coverage: FD `IMP — Structured parse result with confidence, no
    sentinels, no crashes` (fuzz-tested, never raises), FD `IMP — Pure, deterministic parse
    function`. RISK-018.
  - **T-FILE-2 (Tampering — path traversal via destination)**: series/issue titles from ComicVine
    (attacker-influenced) used to build folder/file destination paths; `..`/separators/absolute
    paths could escape the library root. Coverage: LD `META — ComicVine content is untrusted
    input` (sanitized folder names), FD `PP — Token-based renaming engine` (illegal-char policy),
    FD `PP — Folder templates and folder lifecycle`. **Gap G-4a**: no *central path-confinement /
    safe-join* requirement guaranteeing all constructed paths stay within the managed root →
    SEC-new `Filesystem path confinement`. RISK-019.
  - **T-FILE-3 (Tampering — move/delete safety)**: cross-device move, source-delete-before-verify,
    recycle-bin. Coverage: FD `PP — Safe file operations`, FD `PP — Upgrades and deletions via
    recycle bin`. Low residual.
  - **T-FILE-4 (Elevation — script hooks removed)**: Mylar's pre/extra/on-snatch shell hooks are
    an RCE surface. Coverage: FD `PP — Permissions and ownership enforcement` Notes (hooks
    deliberately omitted entirely). RISK-031 (mitigated by exclusion).

---

## COMP 10 — Database (SQLite)

- **Assets**: all application state; secrets stored in settings JSON.
- **Trust boundary**: process → `/config/*.db`; client input → queries.
- **Threats**
  - **T-DB-1 (Tampering — SQLi)**: see T-API-2/T-OPDS-2. Coverage: IF `OPDS — Parameterized
    queries throughout`, IF `API — Paging envelope` (sort-key whitelist). RISK-002.
  - **T-DB-2 (Information disclosure — at rest)**: secrets in the DB file (and backups) readable
    if the volume/backup leaks. Coverage: PF `AUTH — at-rest secret encryption` (key from env, so
    a stolen DB file alone does not expose secrets), PF `DB — pre-migration…`/`scheduled backups`
    (backup handling). RISK-013 (shared).
  - **T-DB-3 (DoS — corruption/lock)**: Coverage: PF `DB — WAL journal mode with busy timeout`,
    `DB — single-writer discipline`, `DB — integrity verification`, `DB — transactional
    multi-step operations`. Low residual.
  - **T-DB-4 (Elevation — schema downgrade/rollback)**: Coverage: PF `DB — refuse to run against
    a newer schema`, `DB — pre-migration automatic backup`. Low residual.

---

## COMP 11 — Secrets / configuration

- **Assets**: ComicVine/DogNZB/NZB.su/SABnzbd keys; OPDS/session/API credentials; encryption key.
- **Trust boundary**: env/`.env`/config file → process; process → logs/diagnostics/DB.
- **Threats**
  - **T-CFG-1 (Information disclosure — in image/repo)**: Coverage: PF `DEP — secrets never in
    image or repository` (CI secret scan), PF `DEP — configuration via environment variables and
    config file`, CLAUDE.md Secrets. RISK-013.
  - **T-CFG-2 (Information disclosure — in logs/diagnostics)**: Coverage: PF `NFR — secret
    redaction in logs and errors`, PF `DEP — secrets-stripped diagnostic bundle`. RISK-013.
  - **T-CFG-3 (Tampering/Elevation — weak at-rest obfuscation)**: Mylar's salted-base64 `^~$z$`
    obfuscation is reversible. Coverage: PF `AUTH — at-rest secret encryption` (AEAD, not
    obfuscation), PF `AUTH — password storage with modern KDF`. RISK-013.
  - **T-CFG-4 (DoS — bad config)**: Coverage: PF `NFR — configuration validation at startup`,
    PF `DEP — versioned config-file migration`. Low residual.

---

## COMP 12 — Scheduler / queues / command bus

- **Assets**: work-item integrity; execution ordering; no duplicate snatches/imports.
- **Trust boundary**: internal, but crash/power-loss is the adversary; command payloads carry
  external ids.
- **Threats**
  - **T-SCHED-1 (Tampering/DoS — lost or duplicated work)**: Coverage: PF `SCHED — persisted
    command queue surviving restart`, `SCHED — command de-duplication`, `NFR — crash-safe queues
    and idempotent work`. RISK-032.
  - **T-SCHED-2 (DoS — starvation/wedge)**: Coverage: PF `SCHED — worker pools per workload
    class`, `SCHED — priority and exclusivity`, `NFR — resilience to external-service failure`.
    Low residual.
  - **T-SCHED-3 (Repudiation)**: Coverage: PF `SCHED — persisted job history` (verbatim failure
    messages — audit trail). Low residual.

---

## COMP 13 — Docker / Tailscale boundary

- **Assets**: the whole service; the `/config`, `/comics`, `/downloads` volumes; the host.
- **Trust boundary**: tailnet → container listener; container → host filesystem/process.
- **Threats**
  - **T-INFRA-1 (Spoofing/Elevation — network exposure without auth)**: the M1/M2 accepted risk.
    Coverage: PF `DEP — Tailscale-scoped exposure` (compensating control), PF `AUTH — M1/M2
    no-auth accepted risk` (canonical accept owner). RISK-020.
  - **T-INFRA-2 (Elevation — container privileges / volume ownership)**: Coverage: PF `DEP —
    Docker image per linuxserver.io conventions` (PUID/PGID, non-root), PF `DEP — all persistent
    state under /config`. RISK-033.
  - **T-INFRA-3 (Information disclosure — listener bind scope)**: binding beyond intended
    interfaces could expose the service off-tailnet. Coverage: PF `DEP — Tailscale-scoped
    exposure` (configurable bind). RISK-020 (shared).
  - **T-INFRA-4 (Tampering — no self-update supply chain)**: Coverage: PF `DEP — no self-update`
    (removes Mylar's git-pull/tarball upgrade attack surface entirely). RISK-034 (mitigated by
    exclusion).
  - **T-INFRA-5 (Availability — DoS surviving restart)**: Coverage: PF `DEP — graceful shutdown`,
    `DEP — health endpoint`, `SCHED — graceful queue drain on shutdown`. Low residual.

---

## Change deltas

### 2026-07-05 — m1-foundation (change 1 of Phase 3)

New attack surface introduced and its disposition:

- **HTTP listener exists** (COMP 1 partial): FastAPI app on 8789 with `/health`
  (unauthenticated by design, FRG-DEP-007) and `/api/v1` skeleton (error shape,
  paging, command endpoints). Auth mode none per FRG-AUTH-001 (RISK-020 acceptance
  restated; route-inventory tests prove no dormant auth paths). WebSocket and OPDS
  listeners are NOT yet present (changes 7).
- **Outbound HTTP choke point** (cross-cutting): all egress flows through one
  factory — mandatory timeouts, TLS always verified, manual bounded redirect walk,
  streaming byte caps (FRG-NFR-006), per-hop SSRF egress validation with
  external/local-service profiles (FRG-SEC-001; RISK-025 mitigated with the
  DNS-rebinding TOCTOU accepted residual recorded in the register).
- **Secrets handling** (COMP 11 partial): SecretStr config fields self-register
  with the log-redaction filter (FRG-NFR-008; RISK-013 log-exposure arm closed);
  no secrets in repo/image (FRG-DEP-005). At-rest encryption remains M3.
- **Persistence + queue surfaces** (COMP 10/12): single-writer WAL SQLite with
  guarded forward-only migrations and pre-migration backups; persisted command
  queue with orphan recovery and graceful drain. No network exposure; failure
  modes are availability-class and covered by tagged tests (FRG-DB-*, FRG-SCHED-*).

No new STRIDE categories beyond those already modeled; component sections above
remain accurate with the M1 subset now implemented.

### 2026-07-05 — m1-library-metadata (change 3 of Phase 3)

New attack surface introduced and its disposition (COMP 8 — ComicVine client, plus
the COMP 9 path-construction threats it feeds):

- **ComicVine client is live** (T-CV-1..6): JSON-only (no XML/expat path exists —
  `T-CV-4`'s XXE concern does not apply to CV traffic at all), built exclusively on
  the change-1 outbound factory (TLS-verify-always, bounded timeouts, `T-CV-2`
  closed), API key sent as a query param but never logged (factory + logging-filter
  redaction, `T-CV-1` closed), honest configurable User-Agent (`T-CV-6` closed).
  A process-global rate limiter serializes all CV traffic including cover fetches
  (FRG-META-003/FRG-NFR-004), which is also the DoS-politeness half of `T-CV-4`.
- **Untrusted CV content sanitized at ingest** (`T-CV-3` closed for the CV arm,
  RISK-011/014): `sanitize_cv_text()` strips HTML/control characters and caps
  length on every string the client maps out of a CV response — no raw wiki HTML
  or CR/LF-forging bytes reach the DB, API, or logs. `T-API-3`/`T-DDL-6` (the
  broader UI-XSS/log-injection threats) remain open for the DDL text arm (change 5).
- **Cover-image SSRF narrowed, not closed** (`T-CV-5`, RISK-025): cover fetches now
  go through the SAME rate-limited, egress-validated outbound client as every other
  CV call, PLUS a config-driven image-host allowlist (`comicvine_image_hosts`) — an
  operator-controlled allowlist rather than trusting an arbitrary wiki-editable
  `image_url` verbatim. The general cross-cutting SSRF-egress-controls gap (G-3) for
  indexer/SAB/pull-source hosts is still open; this change only closes the
  ComicVine-cover-image instance of it.
- **Path construction from CV titles** (T-FILE-2, RISK-019): `safe_path_component()`
  reduces every CV-derived title to one filesystem-safe segment before it is joined
  onto a root folder path (separator/control-char stripping, reserved-name
  de-reservation, trailing dot/space trim); `validate_under_root()` rejects any
  per-series path override outside a registered root. Gap G-4a (a central
  safe-join/containment guarantee against symlink escape and TOCTOU across the
  *whole* destination-path pipeline) remains open, deferred to change 6's renaming
  engine (FRG-SEC-004).
- **New COMP 8 asset**: the local cover cache under `<config>/covers/` — write path
  is a system-generated filename (never derived from the remote URL), closing a
  latent zip-slip-style naming risk before it could ever be introduced.

No new STRIDE categories; COMP 8/9 sections above remain accurate with the M1
subset now implemented. Residual/open items for this component are tracked above,
not re-litigated here.

### 2026-07-05 — m1-search-indexers (change 4 of Phase 3)

New attack surface introduced and its disposition (COMP 4 — indexer clients, plus
the decision engine and release API built on them):

- **Untrusted indexer XML is live and hardened** (`T-IDX-2`, RISK-024/035, gap
  G-2's indexer arm CLOSED): every Newznab response is parsed at a single
  defusedxml site (`indexers/xml.py`) with DTD, external entities, and entity
  expansion disabled, under the factory's response byte cap; the FRG-SEC-002
  hostile corpus (billion-laughs, external-entity, quadratic blowup, oversized,
  junk) is tagged-tested, plus a static guard asserting no other XML-parser
  construction exists in the package. The CBL reading-list arm of G-2 stays open
  (backlog milestone).
- **Indexer-host SSRF instance closed** (`T-IDX-3`, RISK-025 arm): all indexer
  traffic uses `factory.external()` — the change-1 egress profile (loopback/
  private/link-local refusal, TLS verify, bounded timeouts, no auto-redirects).
  SAB/pull-source arms remain for changes 5+.
- **Hostile/slow provider containment** (`T-IDX-5`, RISK-027 CLOSED for
  indexers): persisted per-provider back-off ladder (0s→…→24h, Retry-After/auth
  fast-forward, full reset on success — FRG-NFR-005) honored by every fetch
  path; per-indexer 2s spacing; per-indexer fan isolation in the search
  pipeline so one wedged provider cannot stall the pool — proven by the
  FRG-NFR-010 end-to-end against live hang/drip/junk/429-storm fixture servers
  with a healthy indexer completing in the same command.
- **Indexer API keys** (`T-IDX-1`): SecretStr settings fields, write-only in
  `GET /indexer/schema` responses (never echoed), registered for log redaction
  at row load. Key-in-query-string to the indexer itself is inherent to the
  Newznab protocol; redaction covers our logs/errors.
- **Mislabelled payloads** (`T-IDX-4`, partial): `<error code>` and
  non-XML/HTML responses map to typed failures feeding the ladder; NZB byte
  validation before download-client handoff is change 5 (unchanged plan).
- **New listener surface**: `GET/POST /api/v1/release` (interactive search +
  cached grab) and the series-alias edit path. Release rows are resolved
  strictly from the server-side `release_cache` (30-min expiry, housekeeping
  prune) keyed `(indexer_id, guid)` — a client can only grab something an
  indexer actually returned to *this* server; expired keys are a deterministic
  404-class error, never a silent re-search. Alias edits are ORM-parameterized,
  stored as canonical JSON, and used only via the normalized matching-key path;
  rejection reasons and release titles rendered to the UI remain untrusted text
  (output encoding is the UI's job — unchanged `T-API-3` posture).
- **New assets**: `release_cache` rows (release titles/links from untrusted
  indexers — treated as untrusted text throughout), `provider_backoff` state,
  `series.aliases` (operator-supplied).

### 2026-07-05 — m1-downloads (change 5 of Phase 3)

Two new outbound attack surfaces went live: COMP 5 (SABnzbd client) and COMP 6
(DDL scraper + downloader). Disposition of the STRIDE-relevant threats:

**COMP 5 — SABnzbd client**

- **Server-side NZB fetch + content validation** (`T-SAB-1`/`T-IDX-4`, RISK-028/026):
  the client fetches the NZB bytes itself from the indexer link over the change-1
  `external` egress profile — routed through the indexer's `PROVIDER_INDEXER`
  back-off ladder — and validates them (non-empty, parse under the ONE hardened
  `parse_indexer_xml` defusedxml site reused from FRG-SEC-002, ≥1 `<segment>`)
  BEFORE upload (`_validate_nzb`, FRG-DL-003). A hostile/mislabelled/empty payload
  is a typed `GrabValidationError` and the bytes are never POSTed to SAB; indexer
  credentials never reach SAB. Intake is `mode=addfile` only — Mylar's add-by-URL /
  one-time-download-key callback surface is permanently excluded (`T-SAB-1` closed).
- **Egress split** (`T-SAB-4`, RISK-025 SAB arm): every SAB API call uses the
  change-1 `local_service` profile bound to the operator-configured base URL —
  deliberately permitting the operator's LAN/loopback SAB host (which the strict
  `external` profile would refuse) while keeping TLS-verify, bounded timeouts, and
  the per-hop validation. The compensating control is that the base URL is
  operator-configured, not attacker-supplied. The server-side NZB fetch above,
  by contrast, uses the strict `external` profile (indexer link is remote).
- **SAB API-key redaction** (`T-SAB-3`, RISK-013): the key is a `SecretStr`,
  `register_secret`-registered for log redaction at construction (FRG-NFR-008); it
  rides as an `apikey` query param to SAB (inherent to the SAB protocol) but is
  scrubbed from our logs/errors. At-rest encryption of the stored row remains M3
  (FRG-AUTH-008).
- **Remote-path-mapping confusion** (`T-SAB-2`, RISK-029): a completed `storage`
  path is rewritten through the client's `RemotePathMapping` prefixes; a foreign,
  unmapped path (Windows-shaped on this POSIX host, or any path when mappings exist
  yet none match) is surfaced as a `WARNING` item carrying "check remote path
  mapping" — never a silent import failure, never a crash (FRG-DL-005).
- **Encrypted / corrupt items** (RISK-030 usenet arm): `ENCRYPTED/`-prefixed or
  password-fragment history items map to `FAILED` (+ `encrypted` flag + reason);
  a disk-full unpack maps to a recoverable `WARNING` (FRG-DL-004).
- **Known-bad re-grab defense** (RISK-014 loop / FRG-DL-012): grab rows and the
  failure blocklist now carry `pub_date`, so the multi-field blocklist match key
  actually distinguishes a resurfacing failed release (a missing `pub_date` on
  either side is not treated as a mismatch — `BlocklistEntry.matches`).

**COMP 6 — DDL scraper + downloader**

- **SSRF / egress per-hop allowlist — now covering EVERY scraped fetch**
  (`T-DDL-2`, RISK-007): a per-provider scheme(`https`)+host `AllowList`
  (`build_allowlist` = provider host + `KNOWN_DDL_HOSTS`) is enforced by a
  `hop_check` re-run on every redirect hop, on top of the always-on `external`
  SSRF egress policy. This change extended that gate — previously on the file
  download only — to the scraped **post-page and search-page** fetches too
  (`search_provider._fetch_page`, `queue` post-page fetch via `build_hop_check`),
  closing the residual where a hostile GetComics response could steer a page fetch
  to an arbitrary public host. No cross-host cookies; TLS verify always on
  (FRG-DDL-012).
- **Safe system-generated filenames** (`T-DDL-1`, RISK-006): the on-disk name is
  `{series} {issue} [__{issueid}__]{ext}`, built from library metadata + the queue
  id, every component reduced by the shared `safe_path_component` (FRG-DDL-011 /
  FRG-NFR-012). No redirect-final URL or `Content-Disposition` value ever reaches
  the path (static-tested against a hostile-CD response and a traversal-name
  corpus); `resolve_output_path` is a containment backstop that raises if a name
  ever resolved outside the staging dir. The final extension comes from verified
  magic bytes, never the remote name.
- **Content verification before import** (`T-DDL-5`, RISK-015/030 DDL arm):
  `verify_file` gates every completed file — size floor, magic-byte type
  (zip/rar/pdf), and (for `.cbz`) opens as a real zip with ≥1 image entry, with NO
  extraction (FRG-DDL-010). An HTML ad/error page named as a comic, a truncated
  transfer, or a corrupt archive fails and the queue fails over to the next host.
  Deep malware/AV scanning and supply-chain trust remain the accepted RISK-015
  residual.
- **Politeness + back-off** (`T-DDL-8`, RISK-027 DDL arm CLOSED): page fetches are
  spaced ≥15 s (floor-clamped) plus jitter, with the per-provider last-run
  persisted across restart (`politeness.throttle`, FRG-DDL-006); 429/503, a
  Cloudflare challenge marker, or a connection fault fast-forward the shared
  `PROVIDER_DDL` back-off ladder (FRG-NFR-005). The change-4 note that the generic
  ladder was "ready for DDL reuse" is now realized.
- **TLS always on** (`T-DDL-4` partial, RISK-009): no `verify=False` anywhere —
  all DDL traffic goes through the factory choke point, guarded by a static test
  asserting no `verify=False` exists in `backend/src` (FRG-DDL-012). The Cloudflare
  clearance-cookie / FlareSolverr arm of `T-DDL-4` is NOT live: Cloudflare session
  handling is deferred to backlog B (FRG-DDL-016), so the `.gc_cookies.dat`
  at-rest concern in RISK-009 has no code yet.
- **Scraped untrusted text** (`T-DDL-6`, RISK-014 DDL arm): scraped titles/sizes/
  years become `ReleaseCandidate` fields treated as untrusted text end-to-end —
  same posture as indexer release titles (output encoding is the UI's job). No
  ingest-time HTML/CR-LF sanitizer equivalent to ComicVine's `sanitize_cv_text`
  is applied to DDL text; this arm therefore remains open, not advanced.

**Deferred and still open** — backlog **B**: safe archive extraction of DDL packs
(FRG-DDL-015; `T-DDL-3` / RISK-008 stays open — M1 DDL lands single files only, so
`extractall` never runs), Cloudflare/FlareSolverr session handling (FRG-DDL-016;
`T-DDL-4`/RISK-009 cookie arm), mirror-host adapters (FRG-DDL-017 — Mega/MediaFire/
Pixeldrain never reach the downloader), pack/booktype recognition (FRG-DDL-014).
**Change 6**: import execution and full completed-download cleanup policy
(`mark_imported` is a minimal history-delete stub today).

No new STRIDE categories; COMP 5/6 sections above remain accurate with the M1
subset now implemented. Residual/open items are tracked above, not re-litigated.

### 2026-07-06 — m1-import-pipeline (change 6 of Phase 3)

The change this model was waiting for on two of its named gaps: untrusted archives
are now systematically opened at import time (COMP 7), and destination-path
construction became systematic (COMP 9). FRG-SEC-003/004 land here. Disposition:

**COMP 7 — Archive handling (import arm live)**

- **G-4 closed for the import path** (`T-ARCH-1`/`T-ARCH-2`/`T-ARCH-4`, RISK-010/
  005/030): `security.archives.inspect_archive` is the single shared entry point
  the pipeline's archive-valid decision calls (FRG-SEC-003). All caps are enforced
  on *declared* central-directory metadata before any decompression: member count,
  per-member and total decompressed size, nesting depth 0 (archive-in-archive
  forbidden in M1). Member names in the zip-slip family (absolute, drive-qualified,
  `..`-escaping, backslash-normalized) are rejected, as are symlink entries and
  encrypted archives; a cbz must contain ≥1 image entry. The utility never
  extracts and never raises on hostile input — every rejection is a typed, logged
  `ArchiveReport` the pipeline attaches to the candidate, routing corrupt/password
  archives to failed-download handling → blocklist → re-search (the change-5 loop).
  Hostile corpus (bomb, nested bomb, slip names, symlink, huge member, encrypted)
  committed as fixtures.
- **The honest-flag latent** (found at this gate, fixed a6d29e4): `ok=True` on a
  magic-only cbr/cb7 means "passed the M1 import validity gate", NOT "members
  vetted". `ArchiveReport` now carries `listed` and `safe_to_extract` — the latter
  `True` only when every member was enumerated AND passed the name/symlink/
  nesting/size rules. Any future extractor (FRG-DDL-015 pack extraction, OPDS page
  streaming, cover extraction, tagging) must gate on `safe_to_extract`, never `ok`.
- **Documented residuals (M1-safe: nothing extracts anywhere)**: the RAR listing
  path checks names/sizes/nesting/count but NOT symlink members or RAR encryption
  flags; with `rarfile` absent a CBR passes on magic alone (design decision 4).
  `T-ARCH-3` (PIL truncated-image) is untouched — no image decoding happens at
  import; that arm stays with cover extraction / OPDS streaming.

**COMP 9 — Renamer / file mover (now live)**

- **G-4a closed** (`T-FILE-2`, RISK-019): `security.paths.safe_join(root, *parts)`
  (FRG-SEC-004) is the only sanctioned constructor for destination paths.
  `safe_path_component` relocated here — ONE module owns path safety, no second
  sanitizer copy exists (scenario-tested). Every untrusted part is reduced to a
  single separator-free segment, then the assembled path is realpath-resolved and
  confinement-checked against the root, which also catches escape through a
  pre-existing symlink in the tree; escapes raise `PathConfinementError`. The
  renamer renders folder templates into *segments* handed to `safe_join`. OPDS
  (change 7) swaps onto this same utility when it merges main.
- **`T-FILE-3` implemented** (FRG-PP-007): `place_file` is the one mover —
  same-device atomic `os.replace`, else copy-to-temp *in the destination dir* +
  fsync + size-verify + atomic promote + only-then delete source; a failure at any
  step removes the temp, so no partial ever appears at a final path and the source
  is never lost. Free-space guard (size + margin) runs before any bytes move.
  Upgrades quarantine the superseded file under `<config>/quarantine/<date>/`
  (never deleted — the M1 recycle-bin stand-in); the round-trip renaming contract
  is property-tested so every rendered name re-parses to the same issue identity.

**COMP 12 — Import concurrency / crash-consistency (the gate's atomicity cluster)**

The 9-angle gate review found a real cluster of file-move-inside-rollback-able-
transaction hazards; all fixed (4c943e6, 1b6c3c0, cd9ee93) + regression-tested,
recorded on RISK-032: status-guarded atomic row claim; irreversible on-disk move
ordered BEFORE the DB row swap; per-candidate SAVEPOINT isolation (an escaping
filesystem error becomes BLOCKED, never poisons a sibling's committed row); crash
recovery reconciles FS↔DB and *adopts* an already-placed file instead of orphaning
it; drain and rescan share a file-mutation exclusivity group (double-import safety
no longer rests on pool size 1); manual queue remove refuses (409) an actively-
importing item; per-row failure isolation in the drain.

**New accepted latent** — RISK-040: a still-completed `import_blocked` item is
re-fed to `import_pending` every tracking cycle (the deliberate retry-on-evidence-
change path); each failed retry writes a fresh `import_blocked` history event, so a
permanently stuck item accretes history rows until the user acts. Accepted for M1
(loudly visible in the queue; slow growth); dedup/pruning at the M2 history UI.

### 2026-07-06 — m1-ui-opds-deploy (change 7 of Phase 3)

M1's faces go live: the React SPA (served by the backend), the OPDS 1.2 catalog
(COMP 3), the WebSocket push channel (COMP 2), provider CRUD on the API (COMP 1),
and the Docker/Tailscale deployment boundary (COMP 13). Every COMP 1/2/3 threat now
has running code behind it. Disposition:

**COMP 3 — OPDS catalog (the headline surface, now live)**

- **`T-OPDS` traversal (RISK-001) closed by construction**: downloads are addressed
  only by integer `issue_files.id`; the stored path must pass
  `security.paths.validate_under_root` (the change-6 canonical containment check —
  the OPDS route was swapped onto it at integration) against registered roots
  before a byte streams; out-of-root → 404 indistinguishable from a bad id. No
  parameter anywhere on the surface can carry a path.
- **SQLi (RISK-002)**: all ORM `select` with bound parameters; typed int
  page/count with a server-side page-size cap; no request string reaches SQL.
- **Feed injection**: every untrusted value (series/issue titles, filenames) passes
  the escaping Atom builder; the gate review found and fixed the well-formedness
  gap — XML-1.0-illegal control characters are now stripped, so one poisoned title
  can no longer make a strict reader reject an entire feed page (stored-data DoS).
- **No archive I/O at feed time (RISK-005 arm)**: feeds render from DB rows + the
  change-3 local cover cache only; whole-file downloads stream original bytes with
  comic MIME types. Page streaming (and its resource limits) is M3 and must adopt
  `inspect_archive`.
- **Covers (RISK-023)**: feed image/thumbnail links point at foragerr's own cover
  cache — reader traffic never reaches a third-party CDN. (Thumbnail rel serves the
  full-size cover: bandwidth inefficiency, recorded, not a leak.)

**COMP 2 — WebSocket channel**

- Gate fixes: the connection now registers with the broadcaster BEFORE the
  handshake accept (an event published in the accept window was silently lost);
  debounce coalescing keys on resource identity (two downloads progressing in one
  ~100 ms window both broadcast — the old (name, action) key dropped one row's
  update, which the UI patches by id).
- Per-socket outbound queues are bounded (depth 64; slow client dropped, never
  stalls the bus). **Documented latent (RISK-021)**: no cap on concurrent
  connections and no inbound frame-rate limit — the WS surface is live one
  milestone ahead of FRG-NFR-014 (M2 hardening), accepted for the single-user
  tailnet. Origin validation (`T-WS`/RISK-022, CSWSH) stays deferred to M5 auth as
  recorded. The shipped server can actually speak WebSocket: `websockets` became an
  explicit dependency after Codex found plain uvicorn (click+h11 only) would fail
  every upgrade in the container while the in-process TestClient stayed green.
- Broadcast contents remain `{name, action, resource}` envelopes carrying ids and
  states only — no titles, paths, or secrets ride the channel.

**COMP 1 — API/UI**

- Provider CRUD (indexers, download clients) keeps secrets write-only: GET/list
  never echo stored secret fields; the schema-driven settings UI shows only a
  value-is-stored marker (RISK-013 arm). The SPA static mount serves the built
  bundle; the gate fixed its catch-all to keep real 404s for reserved backend
  prefixes (`/api`, `/opds`, `/health`) instead of masking unrouted paths with
  200 index.html, and `opds_base_path` now rejects reserved mounts.
- One hardening fix behind the API: the root-folder free-space stat runs off the
  event loop, so a hung network mount can no longer stall every listener surface.

**COMP 13 — Docker / Tailscale boundary**

- linuxserver.io conventions: PUID/PGID drop-root, `/config` volume, HEALTHCHECK
  on `/health`, single port 8789. The build script secret-scans the context and
  refuses `.env`-shaped material; the gate widened `.dockerignore` to nested
  `.env` files (a `frontend/.env` with `VITE_*` values would otherwise be inlined
  into the served bundle by a direct `docker build`).
- RISK-020 (no auth) now covers the full live surface — UI, API, OPDS, WS — with
  Tailscale-only exposure as the sole compensating control, made operational by
  the deployment manual: every port-mapping example binds to the tailnet address,
  the do-not-port-forward warning is explicit, and FRG-DEP-011 labelling-control
  tests pin both documents so an edit cannot silently reintroduce an
  all-interfaces example.

### 2026-07-07 — m2-manual-import (M2 change 2)

COMP 7's two remaining anticipated arms go live: untrusted archive METADATA is now
parsed (ComicInfo.xml read, FRG-IMP-024) and archives are REWRITTEN in-process
(ComicInfo tagging, FRG-PP-017). Disposition:

- **ComicInfo read (`T-ARCH` XML arm, RISK-024)**: member selected from the
  already-vetted central directory only (root-level `ComicInfo.xml`), declared-size
  pre-checked against a dedicated 1 MiB cap before any read, read in memory (never
  extracted), parsed exclusively through the generalized single hardened XML site
  (`parse_untrusted_xml`; the static guard forbidding parser construction anywhere
  else passes unchanged). Hostile/malformed metadata degrades to a parse-noted
  empty result — evidence, never an exception.
- **Embedded-id trust**: an embedded ComicVine id only wins reconciliation when
  VERIFIED — it must resolve to an issue already in the library, and in scoped
  contexts belong to the in-scope series; a resolvable-but-conflicting id BLOCKS
  the file as a review item (`EmbeddedIdConflictSpec`) rather than silently
  steering it, and a manual override outranks embedded data everywhere. A hostile
  archive therefore cannot file itself into an arbitrary series: at worst it
  surfaces as a visibly blocked conflict.
- **cbz rewrite (`T-ARCH-2` write arm, RISK-010)**: `tag_cbz` gates honestly on
  `safe_to_extract` (magic-only cbr/cb7 and any unvetted archive are excluded by
  construction), streams member-to-member with a per-member name re-check
  (defense in depth under the inspection) and size caps, writes to a same-dir
  temp with fsync and atomic `os.replace`, and unlinks the temp on ANY failure —
  the placed file is byte-identical on every non-success path. Tagging runs only
  AFTER the import (row + event) has succeeded and can never unwind it. XML
  OUTPUT is built from library records only via the stdlib writer (no parser).
- **Manual import (FRG-PP-016/API-015)**: overrides pin only the series/issue
  mapping and are validated against real rows; the archive/junk/space/upgrade
  safety specs still bind — there is no force path. The listing endpoint resolves
  paths through the canonical containment check against library roots (plus
  tracked-download staging for blocked items); `/config` and arbitrary
  filesystem paths are unreachable, and the folder walk is the same bounded
  intake the rescan uses.

### 2026-07-06 — m2-existing-library-import (M2 change 3)

No new listener, credential, or parser of untrusted input — the change composes
existing hardened surfaces. Disposition:

- **New API endpoints (`/api/v1/library-import/*`, FRG-IMP-023)**: user input is
  only ever a `rootFolderId` / `groupId` / `cvVolumeId` — no endpoint accepts a
  filesystem path, so the FRG-SEC-004 containment posture is inherited without a
  new confinement surface. Match overrides are validated live against ComicVine
  (`get_volume`) before persisting; an unfetchable volume is a 400, a credential
  failure is the static 503 (no key material).
- **Scan walk (FRG-IMP-022)**: the same bounded `iter_archive_files` intake every
  other flow uses, now with junk skipping — walk-time exclusion of dot/AppleDouble/
  unpack-temp artifacts shrinks the set of attacker-influencable names that reach
  the parser; depth bound and race tolerance unchanged. Scan is file-read-only;
  the execute command holds the same `IMPORT_FILE_MUTATION_GROUP` exclusivity as
  every file-mutating flow.
- **Staged imports execute through the SAME `import_candidate` pipeline**: the
  confirmed series mapping enters as an override (mapping only) — the archive/
  junk/space/duplicate safety specs still bind, so a hostile file in a scanned
  library folder gets exactly the manual-import trust treatment (visible block,
  never a force path). Embedded-ComicInfo trust rules from change 2 apply
  unchanged.
- **Duplicate dump folder (FRG-PP-014)**: destinations are built with the same
  `safe_join` confinement as the recycle bin (dated subdirs, collision suffixes,
  no overwrite); the dump root is deliberately NOT a recycle bin (no marker), so
  retention pruning can never delete under it. `duplicate_dump_path` shares the
  recycle-bin path validation (writable dir under operator control).
- **Fixed-release marker parsing**: a bounded regex token rule on the existing
  crash-safe parser (corpus + fuzz discipline apply); no new input channel.

### 2026-07-06 — m2-daily-surfaces (M2 change 4)

**OPDS OpenSearch (FRG-OPDS-007)** puts the first untrusted FREE-TEXT input on
the deliberately unauthenticated OPDS listener (COMP 3): `GET /opds/search?q=`,
advertised via the root feed's `rel="search"` link and a static
`application/opensearchdescription+xml` descriptor. M1 shipped compliant
option (b) — no search advertised; the new surface extends T-OPDS-2
(injection) and the W7 reflected-markup class to a string parameter for the
first time. Disposition:

- **SQL injection**: the term never reaches SQL as text. It is folded through
  the shared `matching_key` normalization and compared only as a bound ORM
  `LIKE` parameter with autoescaped wildcards (`.contains(..., autoescape=True)`
  — a bare `%`/`_` matches literally, not everything); alias matching runs as
  Python substring containment over decoded rows. The existing static guard
  (no `text()`, no interpolated SQL in the OPDS modules) covers the new route.
- **Reflected markup / feed injection**: the term is never echoed into feed
  text; its only reflection is URL-encoded into the search feed's own
  pagination links, emitted through the escaping Atom builder's attribute
  quoting. The OpenSearch descriptor is fully static. No XML parser is
  constructed anywhere (serializer-only, FRG-SEC-002 posture unchanged).
- **Resource bounding**: the term is trimmed to 256 chars before any work
  (oversized input stays a normal, possibly empty, feed — never an error or
  a long reflection); results ride the shared FRG-OPDS-006 page-size clamp.
- **No new data exposure**: results are navigation entries into series
  acquisition feeds already listed by the catalog's own shelves; file access
  remains id-only resolution + root confinement (T-OPDS-1 unchanged). The
  unauthenticated posture is unchanged and remains RISK-003/RISK-020 (M3 auth).
- Adversarial cases (SQL metacharacters, LIKE wildcards, markup payloads,
  10k-char terms) are pinned in `tests/test_opds_security.py`.

The same change also adds `/opds/recent` (a reordering of already-served
acquisition entries — no new input beyond the existing typed page params) and
the delete-files write paths (`DELETE /api/v1/issuefile/{id}`,
`DELETE /api/v1/series/{id}?deleteFiles=true`): id-only parameters, disposal
routed through the existing `safe_join`-confined recycle bin with
files-before-rows compensation (FRG-PP-013 mechanics, no new confinement
surface); destructive scope is bounded to rows the id resolves to.

## Coverage summary

- **Well covered by the five drafts** (mitigation named, no new requirement needed): OPDS
  traversal, OPDS/DB SQLi, OPDS zip-bomb, DDL filename generation, DDL SSRF/allowlist, DDL
  extraction (packs), DDL FlareSolverr TLS + cookie handling, DDL content verification, CV
  key-in-URL, CV TLS-verify, CV/DDL untrusted-string handling, secret redaction/at-rest,
  no-auth accepted risk, parser crash-safety, no-self-update, script-hook exclusion.
- **Genuine gaps requiring NEW SEC requirements** (see `sec-nfr-requirements.md`):
  - **G-1** listener request resource limits (body size / rate).
  - **G-2** hardened XML parsing (XXE / entity expansion) — esp. Newznab/Torznab RSS & CBL.
  - **G-3** SSRF egress controls for ALL server-side fetches (CV cover images + config URLs),
    not only DDL.
  - **G-4 / G-4a** cross-cutting archive-processing safety (bomb/zip-slip limits at import,
    cover extraction, tagging) and central filesystem path confinement/safe-join.
  - **G-5** CSRF stance + WebSocket Origin validation (CSWSH).
