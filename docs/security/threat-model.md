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
