# foragerr — System-wide STRIDE Threat Model (FRG-PROC-006)

Read-only security analysis staged outside the repo per FRG-PROC-008. Feeds the requirements
baseline. Sources: `docs/research/mylar-{opds,ddl,comicvine,filename-parsing,feature-surface}.md`
and the scratchpad drafts `baseline/{library-domain,acquisition,files-domain,interfaces,platform}.md`.

## System context and global trust boundaries

- **Deployment**: single Docker container (linuxserver.io conventions) on a home server;
  Python/FastAPI + SQLite + React. All persistent state under `/config`.
- **Network posture**: reachable only over Tailscale. **M1 shipped with NO application auth** — a
  deliberate, owner-accepted risk whose sole compensating control was the tailnet boundary
  (RISK-020). **Since m8-auth-core (2026-07-12) authentication is MANDATORY on every surface**
  (session/API-key/OPDS-Basic behind a default-deny perimeter, FRG-AUTH-010); the tailnet
  boundary remains as deployment defense-in-depth, no longer a compensating control. At-rest
  secret encryption landed at M6 (FRG-AUTH-008).
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
- **Trust boundary**: tailnet client → listener. No auth before M8.
- **Threats**
  - **T-API-1 (Spoofing/Elevation)**: unauthenticated access to all control endpoints before M8.
    Coverage: PF `AUTH — M1/M2 no-auth accepted risk` (canonical owner of the accept), PF
    `DEP — Tailscale-scoped exposure` (compensating control), PF `AUTH — single-user web login`
    + `AUTH — uniform coverage of all surfaces` (M8 fix, 2026-07-10 reshape). RISK-020.
  - **T-API-2 (Tampering/SQLi)**: injection through client-influenced query values into DB.
    Coverage: IF `OPDS — Parameterized queries throughout` (stated app-wide in spirit); PF
    `DB — typed, sentinel-free schema`; IF `API — Paging envelope` (whitelisted sort keys as
    ORDER-BY defense). RISK-002.
  - **T-API-3 (Tampering/XSS)**: attacker-influenced strings (CV wiki fields, scraped DDL text,
    release titles) rendered in the React UI. Coverage: LD `META — ComicVine content is untrusted
    input`, PF `NFR — untrusted external content handling`. RISK-011, RISK-014.
  - **T-API-4 (Repudiation)**: no auth audit trail before M8; state changes unattributable.
    Coverage: PF `AUTH — login rate limiting and audit`, PF `SCHED — persisted job history`
    (command audit). Gap: no security-event audit before M8 (accepted with RISK-020).
  - **T-API-5 (DoS)**: unbounded request bodies / expensive endpoints; no request-size or
    rate limit on the listener. Coverage: PF `NFR — UI responsiveness at library scale`
    (pagination, no unbounded arrays). **Gap G-1**: no explicit request-body-size cap / listener
    rate limit → FRG-NFR-014 (listener request resource limits). RISK-021.
  - **T-API-6 (Elevation/CSRF)**: state-changing endpoints reachable via forged cross-site
    requests once cookie-session auth exists. Coverage: PF `AUTH — session management` (SameSite,
    HttpOnly). **Gap G-5**: CSRF posture not consolidated; API-key header requests are
    CSRF-immune but the session UI needs an explicit stance → SEC-new `CSRF & WebSocket-origin`.
    RISK-022.
  - **T-API-7 (Information disclosure — log content)**: `GET /api/v1/log` (FRG-API-021, M4
    `m4-logs-viewer`) serves recent backend log records — including acquisition/indexer
    activity, the operator's own debugging trail, and any file paths or hostnames that appear
    in message text — to any tailnet-position reader before M8 auth. Named separately from
    T-API-1 because its mitigation is content-specific, not just the shared no-auth posture:
    the ring-buffer handler that backs it is attached downstream of the secret-redaction
    filter with its own `RedactionFilter` instance (`foragerr.logging_buffer`), so a
    registered secret can never enter the buffer and the endpoint can never serve one,
    independent of auth. Coverage: PF `AUTH — M1/M2 no-auth accepted risk` (same Tailscale-only
    compensating control as every other read endpoint). RISK-043.
  - **T-API-8 (Tampering — containment write endpoints)**: `PUT`/`DELETE
    /api/v1/issues/{issue_id}/collections` (FRG-API-022, M4 `m4-series-detail`) let any
    tailnet-position client declare, replace, or delete trade-containment records
    (FRG-SER-020) — which single-issue series a collected edition declares it collects —
    without authentication. Named separately from T-API-1 because the mitigation is
    scope-specific, not just the shared no-auth posture: containment is display-only by
    construction (a dedicated `issue_collections` side table, no column on
    `series`/`issues`; the FRG-SER-019 absence-test technique is extended to prove
    `wanted_issues`/`series_statistics` never reference it), so a hostile or mistaken
    write can misrepresent what a trade collects but cannot mark an issue owned, flip a
    monitored flag, touch a file, or feed the wanted list/pull matcher. The write is also
    validated against the named series before anything is persisted — target series must
    exist, both endpoint issues must belong to it, bounds must be ordered
    (`ContainmentValidationError` → 400 naming the field) — so a malformed request cannot
    corrupt containment for a series it doesn't name either. Coverage: PF `AUTH — M1/M2
    no-auth accepted risk` (same Tailscale-only compensating control as every other write
    endpoint). RISK-044.

---

## COMP 2 — WebSocket resource-change channel

- **Assets**: live view of library/queue/command state.
- **Trust boundary**: browser → WS endpoint (same listener).
- **Threats**
  - **T-WS-1 (Information disclosure)**: unauthenticated subscription leaks all resource changes.
    Coverage: IF `API — WebSocket resource-change push` (Notes: WS auth is AUTH/M8); PF
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
    (fixed exempt list); until M8, RISK-020. RISK-003.
  - **T-OPDS-4 (Spoofing/MITM — weak auth primitives, Mylar S4)**: plaintext Basic, no TLS
    enforced, no lockout. Coverage: PF `AUTH — password storage with modern KDF` (Basic verifies
    against KDF hash), PF `AUTH — login rate limiting and audit`; TLS via Tailscale (PF
    `DEP — Tailscale-scoped exposure`). RISK-004.
  - **T-OPDS-5 (DoS — zip-bomb / decompression, Mylar S5)**: server-side archive open + PIL
    resize (`LOAD_TRUNCATED_IMAGES`) on untrusted files at feed/stream time. Coverage: IF
    `OPDS — Resource limits on archive and image handling`, IF `OPDS — Cached page counts and
    page index` (no open-every-archive), IF `OPDS — Acquisition feeds…` (no archive I/O at feed
    time). RISK-005.
  - **T-OPDS-7 (DoS/Tampering — malicious RAR, cbr-support)**: CBR page streaming adds a
    RAR parser over untrusted archives. Surface shape: `rarfile` (pure-Python metadata
    parse) + an external `unrar-free` subprocess for member extraction — decompression
    never runs in-process. Coverage: the same archive-limits framework as ZIP
    (member-count / per-member / total declared-size caps enforced from archive metadata
    before any read; single-member streaming extraction only, never full-archive
    extraction to disk; zip-slip/symlink member rejection), magic-byte dispatch (an
    archive is routed by content, never extension), and hard degradation — encrypted,
    zero-member, or unparseable RAR falls back to the non-listable path (no PSE link,
    stream 404) rather than erroring. Backend absence degrades identically. The CBR-to-CBZ convert path (FRG-PP-018) applies the same inspect_archive/safe_to_extract gate and per-entry unsafe-name check before any read, on both the import-time and on-demand routes. RISK-049.
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
    (backup handling). RISK-013/RISK-041 (shared). **Implemented (m6-keystore, 2026-07-12,
    FRG-AUTH-008/011/012/013)**: UI-entered provider secrets are stored `enc:v1:` (Fernet/MultiFernet)
    under a scrypt-derived key from the mandatory env-only `FORAGERR_SECRET_KEY`; only the non-secret
    salt + sentinel are persisted (`keystore_meta`). A decrypt failure fails soft per integration
    (health warning + re-entry), never crashing startup or the library/OPDS surfaces.
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
    obfuscation), PF `AUTH — password storage with modern KDF`. RISK-013/RISK-041.
    **Implemented (m6-keystore, 2026-07-12)**: the divergence-from-Mylar is now live — authenticated
    encryption (Fernet AES-128-CBC+HMAC), not obfuscation, with the key derived from the
    `FORAGERR_SECRET_KEY` passphrase via scrypt. Tampered ciphertext is rejected (HMAC), not silently
    decoded. Residual: a weak operator passphrase (mitigated by scrypt cost + a generated-value
    recommendation in `secrets.md`).
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

## COMP 14 — Store-source clients (Humble Bundle)

- **Assets**: the operator's Humble Bundle session cookie (the most sensitive secret
  foragerr holds — full account access, not scoped); the process (parsing untrusted
  store JSON); the download-staging area and, transitively, the library (a fetched
  entitlement becomes an ordinary import).
- **Trust boundary**: process → `www.humblebundle.com` (order API, operator-pasted
  cookie); Humble order-API response (untrusted JSON) → parser/DB/UI; process →
  the signed-URL CDN host at grab time (FRG-SRC-006).
- **Threats**
  - **T-SRC-1 (Spoofing/Info disclosure — the Humble session-cookie credential)**:
    the `_simpleauth_sess` cookie is the sole authentication mechanism (no password,
    no login automation, FRG-SRC-002) and is as powerful as the operator's own
    browser session. *At rest*: stored as a TOP-LEVEL `SecretStr` on
    `HumbleSettings` (`sources/settings.py`), which rides the same keystore path as
    every other provider secret (FRG-AUTH-008) — `enc:v1:`-encrypted, never
    plaintext in the DB or a backup. *In transit*: sent only as a `Cookie` header to
    `https://www.humblebundle.com` over the shared factory's TLS-verify-always
    `external` profile (FRG-SEC-001), and stripped on any cross-host redirect. *API
    exposure*: write-only — `GET /sources` / connect / reconnect responses report
    only whether a cookie is configured (`public_settings()`), never the value; the
    logging filter redacts it at registration. *Clipboard residual*: the operator
    copies the cookie from browser DevTools and pastes it into the connect card —
    the same OS-clipboard exposure window as any manual cookie-paste workflow, not
    something foragerr's server surface adds or can close (a companion browser
    extension that removes the manual-copy step is recorded as future work — see
    `docs/roadmap.md`, not restated here). Coverage: RISK-045 (at-rest, mitigated —
    cross-references RISK-041's keystore mitigation rather than restating it) +
    RISK-046 (theft blast radius, accepted residual with rationale).
  - **T-SRC-2 (Tampering/DoS — store-controlled JSON parsing)**: the Humble order-list
    and order-detail responses are untrusted JSON from a third party (FRG-NFR-012);
    a compromised or hostile response could attempt an oversized body, a malformed
    shape, or hostile string content designed to corrupt display fields or forge log
    lines. Coverage: byte caps on both response types
    (`ORDER_LIST_MAX_BYTES`/`ORDER_DETAIL_MAX_BYTES`) below the shared factory
    ceiling; pydantic-validated leaf models (`extra="ignore"`, defensive optional
    fields) with hard element caps (`MAX_GAMEKEYS`/`MAX_SUBPRODUCTS`/
    `MAX_DOWNLOAD_STRUCTS`) enforced even within the byte cap; a single malformed
    subproduct is skipped-and-logged rather than aborting the sync, and a
    whole-body shape failure is a typed, caught `HumbleMalformedError` (FRG-SRC-003
    "never crash the scheduler"); every store-supplied display string is sanitized
    through the shared ComicVine ingest sanitizer (`sanitize_cv_text`, FRG-META-014)
    before it can reach the DB, API, or UI — the same HTML/control/CR-LF/Trojan-Source
    stripping RISK-011/014 already established, reused with zero new sanitizer code.
    RISK-047.
  - **T-SRC-3 (SSRF/DoS — signed-URL download egress)**: an accepted entitlement's
    file is fetched from a signed, time-limited URL the order API returns at grab
    time; a compromised/hostile API response could attempt to steer that fetch at an
    arbitrary internal or external host, or serve an oversized/slow payload
    (FRG-SRC-006). Coverage: the signed URL is always fetched FRESH at grab time
    (never a stored/stale value), the fetch is restricted to HTTPS plus the Humble
    CDN host allowlist established by prior-art dissection (`dl.humble.com`,
    `docs/research/humble-api.md`; confirmed at UAT per the proposal's relaxed
    verification constraint) — a URL outside the allowlist or not HTTPS is refused
    and logged, never fetched (mirrors the DDL per-provider allowlist, RISK-007);
    the fetch runs under the shared factory's bounded size/timeout caps
    (FRG-NFR-006); the downloaded bytes are md5-verified against the API-supplied
    checksum before the file reaches the import pipeline, and a mismatch quarantines
    the file into the existing failed-download/retry surface instead of importing
    it. RISK-048.

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
  back-off ladder — and validates them (non-empty, parse under the NZB-specific
  entry point of the ONE hardened defusedxml site, ≥1 `<segment>`)
  BEFORE upload (`_validate_nzb`, FRG-DL-003). *Amended by v0-6-3-fixes
  (2026-07-12, live-SABnzbd finding)*: the NZB 1.1 spec mandates a DOCTYPE, so
  the blanket `forbid_dtd` parse rejected every real NZB; `parse_nzb_xml`
  tolerates that DOCTYPE as inert while keeping entity declarations rejected
  (billion-laughs/quadratic blowup), external resolution disabled (XXE — the
  DOCTYPE identifier is never fetched), and the byte cap unchanged, so the
  RISK-024/035/037 mitigations are unaffected. The carve-out is NZB-only:
  every other surface keeps full DOCTYPE rejection, and the entity-bomb-inside-
  DOCTYPE case is tagged-tested (FRG-SEC-002). A hostile/mislabelled/empty payload
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

### 2026-07-06 — m2-search-autosuggest (M2 change 4.5)

**`GET /api/v1/series/lookup/suggest?term=`** (FRG-API-017, COMP 8 — ComicVine
client) is a new query-string endpoint whose whole point is to be called
frequently as the operator types, which raises a request-amplification /
outbound-DoS consideration on the CV integration (an instance of `T-CV-4`,
RISK-024/036 territory) distinct from the existing full-lookup walk. It reuses
the same outbound egress choke point, the same filter-metacharacter
neutralisation, and the same auth/error mapping as `GET /lookup` — no new
listener, no new parser of untrusted input, no new credential handling.
Disposition:

- **Amplification bounded on three sides**: (1) the frontend gates the request
  on a trimmed term of ≥3 characters AND a ~250 ms debounce
  (`useSuggest`/`useDebouncedValue`), so idle keystrokes never reach the
  network; (2) the server fetch is a single bounded page (offset 0, `limit=10`)
  via one direct `_request` call — `suggest_series` never enters
  `_paginate`'s walk to `_max_pages`, so one suggestion can cost at most one
  upstream page request, tagged-tested; (3) the existing process-global
  ComicVine rate limiter (FRG-META-003/FRG-NFR-004) still serializes this
  traffic alongside every other CV call, unchanged. No new rate-limiting
  mechanism was added or is needed.
- **Error contract reused verbatim, not parallel-copied**: the suggest route
  shares `_comicvine_error_to_api_error` with `GET /lookup` — a
  `ComicVineAuthError` maps to the same static 503 body and
  `field="comicvine_api_key"` discriminator (never the key value, in body or
  log), so the frontend's existing `isComicVineAuthError` classifier drives
  the identical actionable state for both routes. A mid-fetch non-auth failure
  degrades the single page to `complete=false` with no candidates rather than
  raising — there is only one page to lose, so this cannot become a partial
  cascade the way a mid-walk failure could.
- **No new residual risk expected**: this is a bounded, cheap accelerator over
  an already-modeled integration (COMP 8), not a new trust boundary. No new
  `RISK-` row is added, consistent with prior changes that compose existing
  hardened surfaces without introducing new attack surface (e.g.
  m2-existing-library-import).

**Header quick-search** (FRG-UI-019): client-local only — it fuzzy-matches the
already-cached `['series']` React Query data (titles/aliases already delivered
to the browser) with **no network request per keystroke** and no new endpoint.
It adds no attack surface.

### 2026-07-06 — m2-ops-health-backups (M2 change 5)

Four new surfaces, none of them a new listener: scheduled DB+config backup
files on disk (COMP 10 — Database), a startup restore-marker hook (COMP 10 /
COMP 13), and two additive endpoint groups on the existing authenticated
`/api/v1` surface (COMP 1) — system status/health and force-run. Disposition:

- **Backup artifacts (information disclosure, COMP 10 / T-DB-2)**: the
  `backup-database` scheduled task (FRG-DB-009) writes a consistent copy of the
  SQLite DB and the config file to `/config/backups/scheduled-<ts>/` on its
  interval; both files carry the same plaintext provider credentials as the
  live DB/config. This is not a new class of exposure — T-DB-2 already flags
  "secrets in the DB file (and backups)" — but it is the first change that
  actually makes scheduled backups happen, so it is recorded as its own
  accepted risk rather than folded silently into RISK-013: **RISK-041**
  (plaintext provider credentials in database/config backups), accepted for
  M2–M4 on the same footing as RISK-020. Compensating controls unchanged from
  the design: backups are written ONLY under `/config/backups/` (no off-box/
  cloud/download-backup feature exists to move a copy outside the
  container-private volume), they inherit `/config`'s non-root PUID/PGID
  ownership, and credential values are never logged. See
  `docs/security/risk-register.md` RISK-041 for the full acceptance and its
  review trigger.
- **Restore-marker hook (path confinement, COMP 10)**: the startup
  `/config/restore-from` marker (FRG-DB-010, `db/restore.py`) names a backup
  directory to swap in before the engine opens. The marker's raw content is
  attacker-adjacent only in the sense that it is a file an operator (or
  anything with write access to `/config`) can drop — there is no HTTP path to
  it. `_resolve_target` treats the marker's content as untrusted: it is
  resolved against `<config>/backups` and passed through the existing
  `security.paths.validate_under_root` confinement (the same primitive
  RISK-001/RISK-019 rely on), so an absolute path or a `../` escape is refused,
  never followed — the live DB and config are left byte-for-byte untouched on
  refusal, and the refusal is logged loudly. Before any swap, the target
  backup's database must pass a full `PRAGMA integrity_check`
  (`run_full_integrity_check`); a corrupt or missing backup is refused the same
  way. The current live DB (+ config) is snapshotted aside to
  `pre-restore-<ts>/` via the same consistent-backup primitive BEFORE the swap,
  so a bad restore is itself recoverable. The marker is deleted only on a
  completed restore; on a refusal it is left in place but the hook does not
  retry — it simply boots against the untouched live database, so a refused
  marker does not loop, it just needs the operator to fix or remove it before
  the next restart. Consistent with the design's Non-Goal:
  there is deliberately no live/HTTP restore endpoint, so this surface is
  reachable only by an operator with filesystem access to `/config`, not by any
  network client.
- **`/api/v1/system/status`, `/api/v1/health`, `/api/v1/system/health`
  (information disclosure, COMP 1)**: these extend the existing authenticated
  `/api/v1` surface (T-API-1's no-auth acceptance, RISK-020, applies
  unchanged — no new trust boundary). The extended `system/status` payload adds
  runtime info (uptime, Python version, OS) and managed paths (config dir, db
  path, backups dir, root-folder count) — paths only, never a secret value or
  a config field that carries one; the health warnings/component views
  (FRG-API-014/FRG-NFR-011) surface component state, timestamps, and
  remediation-hint text built from static strings and non-secret identifiers
  (provider names, ids, paths) — no provider API key or credential is ever
  read into a `ComponentHealth`/`HealthWarning` value. Both are read-only GETs;
  within the accepted no-auth trust boundary (same tailnet-only exposure as
  every other `/api/v1` route) this is acceptable disclosure of operational
  state to the operator, not a new class of exposure.
- **`POST /api/v1/system/task/{name}` force-run (elevation, COMP 1 / COMP 12)**:
  reuses `scheduler.force_run` verbatim (FRG-SCHED-007) — the same
  enqueue/dedup/timer-reset path every other force-run-shaped action already
  rides, and the same authz posture (T-API-1/T-SCHED-1, unauthenticated within
  the tailnet, RISK-020/RISK-032). No new command-execution surface: an
  unknown task name 404s rather than running arbitrary work, and the only
  effect is enqueuing an already-registered, already-vetted command
  (`backup-database` for "Back up now"). No new `RISK-` row needed for this
  arm — it composes existing hardened scheduler infrastructure exactly as
  m2-search-autosuggest composed the existing ComicVine client.

### 2026-07-06 — m2-first-run-defaults (M2 change 5.5)

Two deltas, both documentation-only over existing hardened surfaces — no new
listener, no new parser of untrusted input, and no new credential handling
primitive. Disposition:

- **ComicVine key-write path (COMP 11 — Secrets/configuration, T-CFG-1/T-CFG-2)**:
  `PUT /api/v1/config/general` (FRG-API-018) is the first endpoint that accepts a
  plaintext secret value from the UI and writes it to `config.yaml`. It reuses the
  EXISTING documented-config writer verbatim (`_apply`: validate → render →
  `atomic_write_text`) — the same at-rest posture `config.yaml` already has for an
  env/file-supplied key (RISK-013 unchanged), on the same no-auth tailnet-only
  trust boundary as every other `/api/v1` write (RISK-020 unchanged, T-CFG-1
  applies unchanged: the value never lands in the image or repository, only the
  operator-writable config volume). The key is never echoed back: `GET
  /config/general` and the PUT's own response report only `{configured, source}`,
  never the value (see FRG-API-018 for the write-only contract) — no new
  disclosure surface. On a successful write the new value is immediately
  re-registered with the log-redaction filter (`register_secret`, the same
  `_apply` step every other config PUT already performs), so T-CFG-2 (secret in
  logs/diagnostics) is covered identically to the pre-existing env/file path — a
  key typed into the UI is redaction-covered from the moment it is accepted, not
  just after a restart. No new `RISK-` row: this composes the existing config-write
  and redaction machinery exactly as `m2-search-autosuggest` composed the existing
  ComicVine client, rather than introducing a new secret-handling code path.
- **Default-on DDL seeding (COMP 6 — DDL scraper + downloader)**: a genuinely
  fresh install now seeds one **enabled** GetComics indexer + one **enabled**
  built-in DDL client (FRG-DEP-013) instead of starting with an empty,
  operator-must-opt-in provider list. This shifts the RISK-015 (single hardcoded
  getcomics.org upstream — a domain takeover becomes a malware-delivery channel)
  and RISK-016 (Cloudflare-evasion/ToS-sensitive scraping automation) postures
  from **opt-in** to **default-enabled** for fresh installs. No new code attack
  surface is added — the DDL scraper/downloader code paths (COMP 6, already
  threat-modeled) are unchanged, `getcomics.org` was already on the hardcoded
  `KNOWN_DDL_HOSTS` allowlist (RISK-007's per-provider allowlist), and the
  default `base_url` is a public HTTPS host, so no egress/allowlist change was
  needed to make the seed safe to run automatically. Mitigations, unchanged from
  the existing RISK-015/016 acceptances but now doing more work because the
  provider is on by default rather than opt-in:
  - the seeded provider pair is **documented** (`docs/manual/user/downloads.md`)
    and **deletable** — deleting either row is permanent, the persisted first-run
    seed marker (`db/first_run.py`, migration `0010_first_run_marker`) ensures a
    user-deleted default is never resurrected on restart, and an **established**
    database (any pre-existing indexer/download-client/series row at migration
    time) is marked already-seeded WITHOUT injecting anything, so an upgrading
    operator is never surprised by a newly-appearing provider;
  - provider rate limits still apply unchanged: `min_interval_seconds=15` between
    GetComics page fetches and `max_pages=3` per search (`GetComicsSettings`
    defaults) — the same politeness ladder (RISK-027) that governs every DDL
    fetch, not a relaxed default-seeded configuration;
  - content verification before import (RISK-015's `Mitigate (partial)` arm) and
    the per-provider outbound allowlist (RISK-007) apply to the seeded provider
    identically to a manually-added one — nothing about being seeded bypasses any
    existing check.
  Review trigger for the shifted posture (recorded in the risk register): any
  exposure of the instance beyond the tailnet, a GetComics ToS change, or a
  malware incident — same triggers RISK-015/016 already carried, now explicitly
  covering the default-enabled state. See `docs/security/risk-register.md`
  **ddl-optin-seeding (2026-07-09): posture reversed to opt-in.** A fresh
  install now seeds the same GetComics indexer + built-in DDL client rows
  **disabled** (automatic-search/RSS toggles off): no scrape, search, grab, or
  download occurs until the operator enables the pair in Settings. Triggering
  event: a 2026-07-09 fresh demo install auto-grabbed live downloads within
  ~1 minute of a library import creating wanted issues. RISK-015/RISK-016
  return to opt-in; installs seeded enabled under the old posture are not
  retroactively disabled. This note supersedes the default-enabled
  description above.
  RISK-015/RISK-016 for the amended wording.
- **Dead credential fields removed (COMP 11)**: `dognzb_api_key`, `nzbsu_api_key`,
  `sabnzbd_api_key` are deleted from the `Settings` model (FRG-DEP-003 modified) —
  they had zero consumers, so removing them shrinks the documented-config surface
  (asset list in COMP 11 above) without changing behavior; per-provider DogNZB/
  NZB.su/SAB credentials are unaffected (they were always stored per-row, never
  read through these fields).
- **LibraryImport credential-error link (FRG-UI-020, client-only)**:
  `frontend/src/screens/library-import/LibraryImport.tsx`'s inline ComicVine
  lookup (`GroupLookup`) now renders the same `<Link to="/settings/general">`
  credential-error guidance as Add Series, reusing the exported
  `OutcomeErrorText` component wholesale rather than a parallel copy. Routing
  only — no new endpoint, no new trust boundary; the underlying classification
  (`isComicVineAuthError`, the structural `errors[].field` discriminator) and
  the 503 it reacts to are unchanged.

### 2026-07-06 — m2-hardening-performance (M2 change 6)

The final M2 change: closes the two gaps this model deliberately left open one
milestone early (G-1's listener limits, and COMP 2's WS documented latent).
Disposition:

**COMP 1 — Web API / UI (`T-API-5`, Gap G-1)**

- **G-1 CLOSED for the HTTP listener** (`T-API-5`, RISK-021): `api/limits.py`
  (FRG-NFR-014) is a pure-ASGI middleware installed in `register_api`, running
  on the **HTTP scope only** (`websocket`/`lifespan` pass through untouched, so
  it can never reach the long-lived WS — that surface is COMP 2, below). Four
  controls, all configurable with generous documented defaults
  (`docs/manual/admin/configuration.md` → "Listener resource limits"):
  header-size cap (`listener_max_header_bytes`, default 16 KiB → 431);
  body-size cap (`listener_max_body_bytes`, default 8 MiB) enforced by a
  streaming byte-counter that aborts at the cap with 413 — a chunked, absent,
  or lying `Content-Length` can never accrue an unbounded buffer; a
  time-to-first-response-byte request timeout (`listener_request_timeout_seconds`,
  default 30s, bounded 503 on expiry, worker released) that is dropped once a
  response starts streaming, so a deliberately-streaming response (an OPDS
  file, an SPA asset) is never truncated by this control; and a per-client
  (peer-address) sliding-window rate cap (`listener_rate_max_requests` per
  `listener_rate_window_seconds`, default 240/1s, `0` disables) backed by an
  LRU-bounded (1024-entry) client table, so the limiter's own memory cannot be
  grown unboundedly by a spoofed-source flood → 429 + `Retry-After`.
- **RISK-014 request arm CLOSED**: any request-sourced value the middleware
  writes toward its own over-limit warnings (method/path/query) passes through
  `sanitize_log_field()`, which reuses the existing `sanitize_cv_text()`
  (FRG-NFR-012) control-character/ANSI stripper, before reaching a structured
  log line — a CR/LF-bearing request path or header can never forge a second
  log line. The DDL scraped-text arm of RISK-014 (GetComics titles/sizes/years)
  is UNCHANGED and stays open, tracked since `m1-downloads`.

**COMP 2 — WebSocket resource-change channel (`T-WS-3`, RISK-021 — the M1
documented latent)**

- **The M1-documented latent is CLOSED**: `WsBroadcaster` (`ws/broadcast.py`)
  gains a configurable `max_connections` cap (`ws_max_connections`, default 32)
  and `try_connect()`, which returns `None` — refusing the connection **without
  mutating the registry or disturbing any live socket** — once
  `connection_count` reaches the cap. `ws_endpoint` (`ws/router.py`) calls
  `try_connect()` and, on refusal, closes the handshake with code `1013`
  **before** `accept()`; below the cap the accepted-connection path (the
  load-bearing register-before-accept ordering, and the `0e0456a` client-gone
  teardown fix) is byte-identical to M1 — no lifecycle regression.
- `_drain_incoming` now bounds the inbound channel (the WS is server-push;
  inbound frames are only a disconnect detector): a frame over
  `ws_max_inbound_bytes` (default 4 KiB) or a burst over
  `ws_max_inbound_messages_per_second` (default 10, sliding 1s window) is
  anomalous and ends the loop, returning with the **client-still-connected**
  disposition, so the endpoint's *existing* `if not client_gone: await
  websocket.close()` teardown performs the single close — no second close path
  was added, and the genuine-`WebSocketDisconnect` → `True` computation is
  unchanged. A tailnet-reachable client can no longer grow listener memory by
  opening unbounded sockets or sending unbounded inbound frames. See
  `docs/security/risk-register.md` RISK-021 for the flipped decision
  (**Mitigate (implemented)**).

**Not new attack surface (test authoring over already-shipped mechanisms)**:
the other four NFR rows this change elaborates — FRG-NFR-001 (startup budget +
a no-outbound-HTTP-during-startup guard + an isolated-importability regression
test pinning the `foragerr.importer` package's existing deferred-import cycle
fix), FRG-NFR-002 (scan-throughput budget), FRG-NFR-003 (UI-latency budget),
FRG-NFR-007 (crash-safety fault-injection) — are budget/regression tests over
mechanisms this model already covers elsewhere (COMP 1 pagination, COMP 12
scheduler/queue persistence). No new listener, no new parser of untrusted
input, and no new credential or outbound-integration path is introduced by any
of the four. The startup change's no-outbound-HTTP-during-startup guard is a
robustness property (a startup hook cannot wedge on an unreachable
ComicVine/indexer host) rather than a new trust boundary, and the
`IMPORT_FILE_MUTATION_GROUP` relocation into a neutral importer leaf is
byte-identical-behavior housekeeping guarding a structural import-cycle
fragility, not a threat closure.

### 2026-07-08 — m3-pull-backbone (M3 change 1)

New attack surface: one outbound integration (the unofficial weekly-pull JSON
source, FRG-PULL-002) and one untrusted-content ingress (ingress #5, the source
JSON). This is the disposition of both — no new STRIDE category, no new COMP, no
new risk id (RISK-039 already reserved this integration).

- **Pull-source SSRF arm CLOSED** (`T-IDX-3`/`T-SAB-4` class, RISK-025 pull-source
  arm, gap G-3's pull arm): the fetch runs exclusively over the change-1 outbound
  factory's **external** profile (`factory.external()`, FRG-SEC-001) — per-hop
  scheme/DNS validation refusing loopback/link-local/private/ULA hosts, TLS verify,
  mandatory timeouts (FRG-NFR-006), auto-redirects disabled. The
  operator-configurable `pull_source_url` is therefore a config-supplied outbound
  host that **cannot** be pointed at an internal service — a loopback/private URL is
  refused per-hop and surfaced as a degraded source, never fetched. The
  DNS-rebinding TOCTOU residual recorded for RISK-025 applies here unchanged; no new
  residual. With `T-IDX-3` (indexer) and the ComicVine-cover arm already closed,
  the only RISK-025 arm now open is the SAB `local_service` host (deliberately
  operator-scoped) — no cross-cutting egress gap remains for external hosts.
- **Untrusted source JSON handled without trust** (ingress #5, `T-CV-3` class for
  the pull arm, RISK-039 tampering half): the response body is **byte-capped and
  stdlib-parsed** (FRG-NFR-012) into the typed pull-entry model; a malformed,
  oversized, or hostile body **degrades to a source-outage outcome without raising
  and writes no partial week** (the per-week replace is transactional — a mid-run
  failure leaves the prior week intact). No XML/expat path exists on this traffic,
  so XXE (`T-IDX-2`) does not apply. Any ComicVine IDs the source supplies are
  recorded as **candidates the matcher still guards** (id match carries a book-type
  guard; name match is sequence/date-window bounded) — the third party is never an
  authority over library identity.
- **Outage/availability contained → degraded-health, not silent failure** (RISK-039
  availability half, FRG-NFR-011 / FRG-API-014): documented source codes are mapped
  explicitly — `619` (bad date) skips only the affected week; `522` (backend down),
  `666` (client-update-required), and transport/timeout failures are treated as a
  source outage that **leaves the previously-stored week intact** and marks the pull
  source **degraded** on the health surface via the shared provider back-off ladder,
  with a remediation hint. The weekly view still renders from local metadata, so the
  third party being down or hostile cannot break the feature.
- **Opt-out preserved** (defence-in-depth): `pull_enabled` originally defaulted
  **off**; since pull-enabled-default (2026-07-11, owner decision) it defaults
  **on** so the Calendar carries release data out of the box. Setting it false
  still issues zero third-party traffic (the scheduled `pull-refresh` task
  no-ops cleanly). Distinct from the RISK-015/016 DDL lesson (ddl-optin-seeding):
  the pull source is metadata-only enrichment — it never downloads content; any
  acquisition still flows exclusively through the operator's own monitor
  policies, seeded-disabled indexers, and the ordinary search pipeline.
- **Storage adds no network surface** (COMP 10): the new `pull_entries` table rides
  the existing WAL-SQLite + guarded-migration discipline (FRG-DB-002/008); entries
  carry only a nullable **link** to a library issue and a `match_type`, never their
  own wanted/downloaded status, so the pull side is a read-through projection and
  cannot flip issue state (the refresh trigger enqueues the ordinary `refresh-series`
  command; wanting is decided by the series' monitor policy).

RISK-039's mitigation is thereby **realised** (timeouts, documented error-code
handling, degraded-health surfacing, untrusted-JSON treatment) and RISK-025's
pull-source arm **closed** via the external egress profile. Both are updated to
implemented-status in the risk register; no new risk id and no SOUP change (the
fetch reuses the existing `httpx` factory; parsing is stdlib).

### 2026-07-08 — m3-opds-page-streaming (M3 change 3)

New attack surface on **COMP 3 — OPDS catalog server**: the first server-side
**archive-open + image-decode** path reachable from the OPDS listener (previously the
M1 catalog served whole files with zero archive I/O and no image library). Two new
GET endpoints — `/page/{issue_file_id}/{pageNumber}` (PSE single-page stream) and
`/cover/{issue_file_id}` (local first-page cover) — read and decode untrusted archive
bytes from library files. No new STRIDE category, no new COMP, and **no new risk id**
(RISK-005 already reserved this surface). Disposition:

- **T-OPDS-3 (DoS — zip-bomb / decompression / pixel-bomb / truncated image),
  RISK-005 CLOSED**: both endpoints open archives ONLY via `security.archives`
  (`list_image_members`/`read_image_member`) — central-directory member/byte caps from
  `inspect_archive`/`ArchiveLimits`, gated on `safe_to_extract` (never `ok`), declared-
  member-size checked **before** read, `is_safe_member_name` re-checked per member
  (zip-slip defence-in-depth). Decode is ONLY via `security.images.render_page`, which
  sets `Image.MAX_IMAGE_PIXELS`, keeps `LOAD_TRUNCATED_IMAGES` **off**, and rejects an
  over-pixel image **before** `.load()`. A **per-request wall-clock time bound**
  (`asyncio.wait_for` over an offload thread) turns a pathological decode into a 503,
  not a pinned core. Every cap is operator-configurable (`opds_pse_*`). The M1
  **no-archive-I/O-at-feed-render** invariant is preserved — `pse:count` comes from the
  cached `issue_files.page_count`, never from opening the archive at render (a NULL
  count is filled lazily on first stream, off the render path).
- **T-OPDS-1 (Information disclosure — path traversal) unchanged/closed**: both new
  endpoints resolve strictly by `issue_file_id` through the same `validate_under_root`
  confinement resolver as whole-file download (FRG-OPDS-003) — no request field is ever
  used as a filesystem path; `pageNumber`/`width` are integers, bounds-checked.
- **Reduced egress (privacy)**: the local cover/thumbnail fallback means a cover-less
  issue no longer hotlinks a ComicVine CDN URL to the reader — thumbnails are served by
  the application, so a tailnet reader makes no third-party request.
- **New dependency**: **Pillow** is added (SOUP register updated, FRG-PROC-012) — used
  ONLY on these two OPDS decode paths under the caps above, never wired into import,
  metadata, or the UI. `rarfile` is deliberately NOT added: a CBR is unlistable, so it
  gets no PSE link and no local cover (whole-file download unaffected) — avoiding a
  shell-out-to-`unrar` surface.

RISK-005 and the cover-extraction arm of RISK-010 are updated to implemented-status in
the risk register; COMP 3 above remains accurate with the streaming subset now live.

### 2026-07-10 — m4-logs-viewer (M4, owner-requested)

New attack surface on **COMP 1 — Web API/UI**: one new read endpoint, `GET
/api/v1/log` (FRG-API-021) — the first surface that serves backend LOG CONTENT
itself (as opposed to log-derived application state) to a client. No new STRIDE
category, no new COMP; one new risk id (RISK-043), because the mitigation this
row records is specific to log content, not just the shared no-auth acceptance.
Disposition:

- **T-API-7 (Information disclosure) — mitigated by construction, not by auth**:
  the in-memory ring-buffer handler (`foragerr.logging_buffer.install_log_buffer`,
  design decision 3) is attached to the root logger AFTER
  `foragerr.logging.setup_logging` has configured the stdout/file handlers, and
  it carries its OWN `RedactionFilter` instance. Python's
  `logging.Handler.handle()` always runs a handler's own filter immediately
  before that same handler's `emit()`, so every record is redacted before it can
  reach the deque — independent of how many other handlers exist on the root
  logger or in what order they run. A registered secret (ComicVine, indexer, or
  SABnzbd key) can therefore never enter the buffer, and `GET /api/v1/log` can
  never serve one, regardless of the no-auth posture. Proven by a tagged test:
  a log call carrying a registered secret value produces a buffered/served
  record with the secret masked.
- **Same accepted posture, no new auth surface (RISK-020 lineage)**: the
  endpoint is read-only, unauthenticated, and reachable only over the tailnet —
  identical posture to every other read endpoint accepted under RISK-020. It
  adds no new listener, no new credential, and no new outbound integration.
  Because raw backend log text (file paths, third-party hostnames, internal
  error detail) reads as more sensitive than a typical structured API response,
  this gets its own risk row (RISK-043) rather than silently folding into
  RISK-020 — the compensating control (Tailscale-only exposure) is unchanged.
- **Bounded, not durable (FRG-NFR-015)**: the buffer is capacity-bounded
  (`log_buffer_records` / `FORAGERR_LOG_BUFFER_RECORDS`, default 2000,
  fail-fast-validated at startup) and memory-only — a restart clears it, so
  this is not a durable exposure surface, and capture is O(1) per record so it
  cannot be used to exhaust memory.
- **No new WS surface (design decision 2)**: the Logs screen polls the resource
  rather than subscribing to a push — a log→push→error→log feedback loop (a WS
  error is itself logged) is designed out rather than mitigated at runtime, so
  COMP 2 (WebSocket channel) gains no new attack surface from this change.
- **Audit-trail position recorded, not implemented (FRG-NFR-015 Notes)**: this
  is an operator observability surface, not an audit log — durable,
  attributable access/audit logging (who did what, tamper-evident, retention
  policy) is deferred to the auth milestone (M8), when there are distinct
  principals to attribute actions to.

RISK-043 is added (new) for this row; it cites RISK-020 for the no-auth
acceptance rather than restating it. No new SOUP (stdlib `logging` +
`collections.deque` only; `tools/soup_check.py` unaffected).

### 2026-07-10 — m4-series-detail (M4 ch4)

New attack surface on **COMP 1 — Web API/UI**: two new write endpoints, `PUT`/`DELETE
/api/v1/issues/{issue_id}/collections` (FRG-API-022), plus the read-only `GET
/api/v1/series/{series_id}/collections` rollup and collected-in chips folded into the
existing issues listing — the trade-containment model (FRG-SER-020). No new STRIDE
category, no new COMP; one new risk id (RISK-044), because — like RISK-043 before it —
the row records a mitigation specific to this write surface, not just the shared
no-auth acceptance. Disposition:

- **T-API-8 (Tampering) — mitigated by scope, not by auth**: containment is
  display-only by construction (FRG-SER-020): a dedicated side table
  (`issue_collections`) carries no column on `series`/`issues`, and the FRG-SER-019
  never-suppress-wanted absence-test technique is extended so the compiled SQL of
  `wanted_issues`/`series_statistics` is asserted to never reference it. So an
  unauthenticated write can misrepresent what a trade collects but cannot mark an
  issue owned, flip a monitored flag, touch a file, or feed the wanted list/pull
  matcher — the same invariant that already protects trade-typing (m3-trade-typing)
  extends to containment. The repo layer
  (`foragerr.library.containment.replace_issue_collections`) also validates every
  write BEFORE touching a row — the target series must exist, both endpoint issues
  must belong to it, and the bounds must be ordered — rejecting otherwise with the
  standard 400 error shape naming the field, so a malformed request cannot corrupt
  containment for a series it doesn't name either.
- **Same accepted posture, no new principal (RISK-020 lineage)**: the endpoints are
  reachable only over the tailnet, identical posture to every other write endpoint
  already accepted under RISK-020. They add no new listener, no new credential, and
  no new outbound integration.
- **Negligible information disclosure**: the collections/chips reads return only data
  the operator already declared and can already see on the detail screen (trade
  identity, book-type, range labels, request-time coverage) — nothing not already
  visible is newly exposed.
- **Cascade cleanup, not a new deletion surface**: containment records are removed
  automatically when their trade issue or target series is deleted (FK CASCADE,
  FRG-SER-020) — no operator-facing delete action beyond the containment dialog's own
  Delete/Delete-all.

RISK-044 is added (new) for this row; it cites RISK-020 for the no-auth acceptance
rather than restating it. No new SOUP (SQLAlchemy ORM + the existing repo/session
patterns only; `tools/soup_check.py` unaffected).

### 2026-07-12 — m6-humble-source (M6, first M6 change)

New attack surface on a new **COMP 14 — Store-source clients (Humble Bundle)**: the
first outbound integration authenticated with an operator-pasted session cookie
(not an API key), the first parser of store-controlled JSON, and (per FRG-SRC-006)
the first signed-URL download path outside the existing indexer/SAB/DDL surfaces.
Three new risk ids (RISK-045..048 — four ids, one of which is an accepted residual
rather than a mitigation). Disposition:

- **T-SRC-1 (cookie credential) — mitigated by the same construction as every other
  provider secret, closed for the arms foragerr's own surface controls**: keeping
  `session_cookie` a TOP-LEVEL `SecretStr` on `HumbleSettings` means the m6-keystore
  machinery (FRG-AUTH-008, merged first as this change's hard dependency) encrypts
  it at rest with zero source-specific code — RISK-045 cross-references RISK-041's
  keystore mitigation rather than restating it. Write-only API exposure and TLS-only
  transit are implemented exactly as design decision 1/9 specified. **The residual
  this row cannot close**: once pasted, the cookie IS the operator's live Humble
  session — full account access, not a scoped token, because Humble does not offer
  one. RISK-046 accepts this with rationale (session cookies expire on the order of
  weeks; the operator can invalidate the session, and therefore foragerr's copy of
  it, by logging out of Humble in the browser at any time — the next sync surfaces
  as `expired`, FRG-SRC-005; no payment/billing action is reachable through the
  order-list/order-detail API surface this client exercises) and a review trigger
  (reported unauthorized account activity, or Humble introducing a scoped token).
- **T-SRC-2 (store-JSON parsing) — CLOSED**: `sources/humble.py` byte-caps both
  response types, validates every leaf through pydantic with defensive defaults,
  hard-caps element counts even within the byte cap, skips-and-logs a single
  malformed subproduct rather than aborting the sync, and reuses the ComicVine
  ingest sanitizer (`sanitize_cv_text`) on every store-supplied display string —
  extending the RISK-011/014 untrusted-text posture to a new source with no new
  sanitizer code. RISK-047.
- **T-SRC-3 (signed-URL egress) — specified, implementation lands in this same
  change**: FRG-SRC-006 (fresh URL at grab time, HTTPS + Humble CDN host allowlist,
  bounded size/timeout, md5 verification, checksum-mismatch quarantine) is recorded
  here ahead of/governing the download-worker task (tasks.md 4.1) that implements
  it — per FRG-PROC-006, the STRIDE/risk-register update for a new outbound
  integration is required in the same change that introduces it, and this change is
  the same change. RISK-048.
- **Comic/other classification is not a security control**: `sources/classify.py`'s
  platform/format rule (design decision 4) determines what the UI shows by default,
  not what is trusted — non-comic items are retained, never dropped (FRG-SRC-003),
  so a misclassification is a discoverability question, not an attack surface.
- **New dependency: none.** The Humble client is built entirely on the existing
  outbound HTTP factory, pydantic, and the shared sanitizer; no SOUP register change.
- **Session expiry as a modeled state (FRG-SRC-005) also closes a DoS/repudiation
  concern for free**: a 401 mid-sync flips the source to `expired` and the
  `source-sync` handler skips every non-`connected` source on later ticks (see
  `sources/commands.py::_handle_source_sync`) — there is no retry storm against a
  dead session, and the failure is recorded (`last_sync_status`) rather than
  silently swallowed.

RISK-045, RISK-047, and RISK-048 are added as **Mitigate**; RISK-046 is added as
**Accept (residual)**. No new STRIDE category beyond Spoofing/Info
disclosure/Tampering/DoS/SSRF, all already modeled elsewhere in this document.

### 2026-07-12 — m8-auth-core (M8 change 1)

The milestone that ends the RISK-020 acceptance. New attack surface: a credential
parser on an exempt route (login), a session store, cookies in the browser, and a
bootstrap path that consumes credentials from the environment. New session/cookie/
CSRF rows; G-5 closed; FRG-AUTH-001 retired. Disposition:

- **T-AUTH-1 (Spoofing — credential guessing at the exempt login route)**: the only
  unauthenticated POST surface in the application. Mitigations in this change:
  scrypt verification cost (~170 ms, n=2^17) bounds online guessing throughput per
  connection; failures are uniform (`401 {"message":"invalid credentials"}` for
  unknown-user and wrong-password alike, with one KDF operation on every path, so
  neither response body nor timing distinguishes them). **Closed (`m8-rate-audit`,
  2026-07-12)**: per-(IP, surface) failure counters with exponential 429+Retry-After
  backoff run BEFORE the KDF on this route (FRG-AUTH-009) — see the m8-rate-audit
  status note below for the full disposition.
- **T-AUTH-2 (Spoofing/Elevation — session token theft or fixation)**: tokens are
  256-bit random, stored server-side only as SHA-256 (a DB/backup leak reveals no
  usable token); the raw token exists only in an HttpOnly SameSite=Lax cookie
  (script-unreadable, cross-site-unsent); login regenerates the token so a
  pre-login fixated cookie never authenticates; logout and password re-seed delete
  rows server-side (replay after logout is a tagged test). Remember-me (90 d
  sliding) widens the theft window by design — owner-accepted comfort decision,
  default-not-floor, configurable down. `Secure` flag is conditional on transport;
  TLS remains DEP's story (documented in the manual).
- **T-AUTH-3 (Elevation/CSRF — riding the operator's ambient session)**: closed by
  FRG-SEC-005 (see RISK-022): Origin/Referer check on cookie-authenticated unsafe
  methods (foreign AND absent Origin refused, 403 before any side effect),
  SameSite=Lax as the second layer, API-key surface immune by construction, WS
  Origin allowlist pre-upgrade. T-API-6 and the COMP-2 WS Origin gap both resolve
  here.
- **T-AUTH-4 (Info disclosure — credential material at rest / in logs)**: passwords
  and the OPDS password stored only as salted scrypt strings; the API key only as
  SHA-256 (high-entropy input needs no KDF); bootstrap env values are
  redaction-registered for the process lifetime (FRG-NFR-008), and a tagged test
  captures logs across seed/login/failure/re-seed asserting no credential material.
  The one-shot `bootstrap-key` endpoint holds the raw API key in process memory
  only, requires an authenticated session, and 404s after first read and after
  restart.
- **T-AUTH-5 (Elevation — a route that forgot the perimeter)**: the classic
  regression is prevented three ways (FRG-AUTH-010): the dependency is installed at
  the application root so new routers are born covered; an exhaustive
  route-inventory test walks `app.routes` asserting every route is exempt-listed
  (exactly `/health` + `/api/v1/auth/login`) or refuses bare requests; e2e negative
  paths exercise each surface. FastAPI's built-in Swagger/redoc routes (plain
  Starlette routes the dependency cannot cover) were removed and `openapi.json`
  re-served as an authenticated route — the schema no longer leaks unauthenticated.
  Static SPA mounts stay exempt by construction and serve only static UI code.
- **T-AUTH-6 (Tampering/DoS — hostile input to the auth parsers)**: login accepts a
  small JSON body on an exempt route; body size is bounded by the existing listener
  limits (G-1 controls), pydantic-validated, and touches only the principal row.
  Basic-auth parsing on OPDS uses the standard header decode with the same uniform
  failure. The scrypt cost that defends T-AUTH-1 also bounds attacker-imposed CPU
  per request (one KDF op, no amplification).
- **Bootstrap env credentials (environment trust class)**: `FORAGERR_ADMIN_USER`/
  `FORAGERR_ADMIN_PASSWORD` (+ optional `FORAGERR_OPDS_PASSWORD`) join
  `FORAGERR_SECRET_KEY` in the same trust class — visible to whoever can read the
  compose file/environment, which is already the deployment's root of trust
  (documented together in the manual's secrets page). Re-seed-on-change is the
  deliberate lockout-recovery path; it invalidates all sessions and logs a
  structured event without credential material.
- **New dependency: none.** scrypt comes from the already-SOUP'd `cryptography`;
  sessions/principal ride SQLite; no SOUP register change.
- **Gate-round hardenings (full 8-angle fleet + Codex, 2026-07-12)**: the KDF is
  offloaded off the event loop (`anyio.to_thread.run_sync`) so the every-request
  OPDS Basic verify cannot head-of-line-block the server (T-AUTH-6 amplification
  bound); `bootstrap-key` moved GET→POST so the consuming one-shot read carries
  the CSRF Origin check (a cross-site GET could otherwise burn the operator's
  retrieval); the `principal` table gained a `CHECK (id = 1)` singleton so two
  instances on one DB cannot both seed a valid account; the login-redirect
  `?return=` guard resolves against the real origin (a substring guard let
  `/\evil.com` through and crashed the SPA on a cross-origin history mutation);
  logout now returns the cookie-deletion response so the stale cookie is cleared
  client-side. All five are covered by tagged tests.

RISK-020 flips **Accept → Mitigated** (rate-limit/audit residual noted on the row,
owned by `m8-rate-audit`); RISK-022 flips to **Mitigated**; RISK-003 notes the OPDS
Basic realm is live (credential-independence lifecycle flips with FRG-AUTH-005 in
`m8-keys-opds`); RISK-043/044 close their RISK-020-lineage accept-residuals.

### m8-keys-opds status (2026-07-12, v0.8.0)

Credential lifecycle lands (FRG-AUTH-005/006/007 implemented): in-app admin
password change (acting session preserved, all others invalidated), independent
OPDS password change, API-key display-once rotation, logout-all. Security-relevant
deltas on the shipped model:

- **Uniform re-auth on credential writes.** Every credential-changing endpoint
  requires the current admin password in the request body; a ridden session
  alone cannot mint a durable credential or lock the operator out. Failures are
  a single generic 403 with no field oracle, structured-logged
  (`auth.reauth_failed`) for `m8-rate-audit`'s counters. Logout-all deliberately
  requires no re-auth: it grants nothing (pure session destruction) and is the
  shared-device recovery, where friction favours the attacker.
- **Env re-seed fingerprints** (closes the core gate's deferred footgun): boot
  re-seed now compares the env pair against a stored scrypt fingerprint of the
  pair *as last seeded*, per credential (admin and OPDS decoupled). A stale env
  var can no longer silently revert an in-app change (an unlogged credential
  rollback + session wipe — an integrity/DoS hazard); recovery still works by
  supplying a value the environment has not seeded before. The fingerprints are
  scrypt hashes stored beside the live hashes — same protection class, no new
  disclosure surface.
- **OPDS Basic verify-cache.** Positive-only, in-process, 60 s TTL, capacity 8,
  keyed by SHA-256 of the presented `username\0password`, cleared synchronously
  on every credential write. Negative results are never cached (no
  wrong-credential pinning, no stale-deny after a change). Residual: a
  credential changed by DIRECT database edit (outside the app) could verify for
  up to 60 s — out of threat model (arbitrary DB write is already game-over).
  The wrong-username path still runs the KDF on cache misses, preserving the
  timing uniformity shipped in core.
- **Display-once API key.** The raw key exists only in the bootstrap one-shot
  and the rotate response; at rest only its SHA-256. The frontend confines the
  rotate response to component state (`gcTime: 0` + `.reset()` on the mutation so
  neither the raw key nor the submitted admin password survives in React Query's
  MutationCache), verified by a tagged test that the key is absent from the DOM,
  the query cache, the mutation cache, and localStorage after the dialog closes.

**Gate-round findings fixed in-branch (full 10-angle fleet + Codex, 2026-07-12):**

- **OPDS verify-cache TOCTOU (LOW–MED, fixed).** The KDF awaits, so a credential
  write could land mid-verify; a verify that captured the old credential could
  then re-seed its now-stale positive *after* the clear, keeping an old OPDS
  password valid for up to the 60 s TTL. Fixed with a generation counter: `clear`
  advances it, the verify captures it before reading the principal, and `put`
  drops the write if a clear intervened. Concurrency test added.
- **Frontend MutationCache retention (MED, fixed).** See the display-once note
  above — the raw key and admin passwords lingered in the MutationCache for the
  default 5 min; `gcTime: 0` + `.reset()` close it.
- **Hardening:** `current_password` is length-capped before the re-auth KDF (was
  an unbounded self-inflicted amplifier); the verify-cache key is now a
  length-unambiguous digest-of-digests (removes a theoretical field-boundary
  collision class); a rotation drops any never-retrieved bootstrap key.

**Accepted residuals:**

- **Re-auth confirmation path CPU pressure (accepted, out of FRG-AUTH-009 scope).**
  `m8-rate-audit`'s limiter is wired at the three *unauthenticated* credential-
  bearing surfaces named in its design (login, `X-Api-Key`, OPDS Basic) — the
  `_reauth_admin` confirmation used by password-change/OPDS-password-change/key-
  rotation is deliberately out of scope (the caller already holds a valid
  session; the length cap on `current_password` still bounds the per-request KDF
  cost). An *already-authenticated* caller firing parallel wrong-password
  confirmation requests can still drive concurrent memory-hard KDFs (anyio's
  default limiter). Accepted: this requires a live session first, so it is not a
  remote-unauthenticated DoS, and no further M8 change is scoped to it (hard stop
  at M9 per the standing grant); revisit if abuse is observed.
- **Verify-cache is per-process.** Clearing it on a credential write clears one
  worker's cache. The reference deployment runs a single uvicorn process, so this
  is a non-issue today; were the image ever run with `>1` worker, an OPDS
  password rotation would leave a stale positive live for ≤60 s in workers that
  did not serve the write. Sessions are DB-backed and unaffected. A one-line
  caveat for any future multi-worker mode.

### m8-rate-audit status (2026-07-12, v0.9.0)

Failed-auth throttling and a unified audit vocabulary land (FRG-AUTH-009
implemented) — the last M8 auth change. Security-relevant decisions on the
shipped model:

- **Brute-force mitigation: backoff, not lockout.** Sliding-window counters per
  (client IP, surface) refuse further attempts on a key after 5 failures in a
  15-minute window with a 429 + `Retry-After` deadline that doubles per excess
  failure, capped at the window length. Deliberately no hard lockout: this is a
  single-operator tool, so an attacker who could force a *permanent* refusal
  would be handed a denial-of-service against the legitimate operator — a worse
  outcome than temporarily slower guessing. A success resets the key; env
  re-seed remains the recovery of last resort for a lost credential, unrelated
  to this counter.
- **Client-IP trust boundary.** The enforcing and observation counters key on
  `request.client.host` — the direct TCP peer — only. `X-Forwarded-For` is
  deliberately never parsed or trusted: the deployment model is a bare uvicorn
  process on a tailnet with no reverse proxy in front of it, so there is no
  trusted hop to have set that header, and honoring an attacker-supplied
  `X-Forwarded-For` would let a single attacker spray failures under forged
  identities to dodge the per-key counter entirely. Revisit if the deployment
  model ever adds a documented reverse-proxy story (DEP's TLS/proxy work).
  **Deployment caveat (gate finding S1, m8-rate-audit):** the per-IP isolation
  that stops an attacker from throttling the operator only holds when foragerr
  observes *real* peer addresses. Under Docker bridge networking with the
  userland proxy enabled, the container can see the bridge gateway IP as the
  source for every external client — collapsing operator and attacker onto one
  `(gateway-IP, login)` key, so an in-tailnet attacker's login-failure burst
  can 429 the operator's own login until the deadline expires. The surface
  split still isolates login from OPDS/API, and the refusal is temporary (no
  hard lockout; restart or deadline expiry recovers), so this is a
  defence-in-depth degradation, not an authentication bypass. Mitigation is
  operational and documented in `docs/manual/admin/network.md`: run with
  `network_mode: host`, Tailscale inside the container, or a source-preserving
  DNAT (`userland-proxy=false`) so the limiter keys on genuine client IPs. The
  same shared-bucket failure mode arises if the ASGI server never populates
  `scope["client"]` (the IP resolves to the literal `"unknown"` for every
  caller); the mitigation is identical, and in practice the direct-uvicorn
  deployment always populates it.
- **Log-injection hardening.** The one attacker-controlled string that reaches
  an audit event — the submitted username — is stripped of every C0/C1 control
  character (newlines, carriage returns, ANSI escape introducers) and length-
  capped before it is rendered (`auth/audit.py::sanitize`), so a crafted
  username can neither break the fixed `<event> key=value …` log line nor forge
  a second event inside it. Messages are pre-rendered strings (no `%`-style log
  interpolation), so a username containing `%` cannot trigger format-string
  behavior either. Tagged tests cover newline/ANSI/oversized-username inputs.
- **Limiter shields the constant-work KDF from failure-flood CPU exhaustion.**
  The limiter check runs on all three credential-bearing surfaces (login,
  `X-Api-Key`, OPDS Basic) *before* any scrypt verification — a throttled key
  never reaches the deliberately constant-work KDF path, so a failure flood
  against a single key cannot be used to burn CPU the way it could before this
  change (T-AUTH-6 amplification bound, extended). The re-auth confirmation
  path used by password/OPDS-password change and key rotation is out of this
  scope (see the accepted residual below).
- **Global counter is observation-only by design (anti-operator-DoS).** A
  second, per-surface counter tracks failures across *all* keys but never
  blocks — only the per-(IP, surface) counter enforces. This is deliberate: if
  the global counter could block, an attacker spraying failures from many
  spoofed or botnet source addresses could drive the shared surface counter
  over threshold and lock the real operator out of their own login, turning a
  distributed guessing attempt into a denial-of-service against the legitimate
  user. Instead, crossing the global threshold only emits
  `auth.backoff_triggered` (rising edge, once per hot period) so a distributed
  pattern is visible in the audit trail with no enforcement action attached.
- **Leaked-key visibility via `auth.apikey_source_seen`.** Per-request API-key
  success events would be pure log noise (a programmatic client hits every
  endpoint), so successful key use is audited *per source* instead: a TTL'd,
  bounded seen-set of source IPs emits the event only on the first successful
  use from a given address within the window, and key rotation clears the set
  so a rotated key gets a fresh baseline. This closes an observability gap a
  stolen-but-still-valid key previously had — it now surfaces in the audit
  trail on its first use from any new address, at near-zero log volume,
  without the operator needing to review every successful request.
- **New dependency: none.** Stdlib only (`collections.OrderedDict`/`deque`,
  `time.monotonic`); no SOUP register change.

RISK-020's residual note (rate-limit/audit landing in `m8-rate-audit`) is now
closed; see the row for the final disposition.

### 2026-07-14 — humble-session-extension (0.9.x dogfood)

A companion browser extension (Chrome + Firefox, Manifest V3) whose entire job is
to read the operator's own Humble `_simpleauth_sess` cookie on an explicit click and
place it on the system clipboard, so the operator pastes it into the existing Sources
connect/reconnect card. **Owner decision 2026-07-14: clipboard-only.** An earlier
draft had the extension POST the cookie to a new authenticated foragerr endpoint using
a stored API key; that shape was rejected — the extension does not connect back to
foragerr, holds no API key, and makes no network request of any kind. There is no
backend change: the existing manual-paste path is the only ingestion route.

New elements: **E-EXT** (the extension in the browser profile), **E-DIST** (the
self-distributed artifact). Because the extension has no network capability and stores
no credential, the connected-extension threats (API-key-at-rest, transit interception,
cookie-to-wrong-instance) do not exist here.

- **T-EXT-1 (clipboard residual) — accepted, folds into RISK-046.** The cookie is
  briefly on the system clipboard so the operator can paste it into the connect card;
  a malicious co-installed extension with `clipboardRead` or a clipboard-manager app
  could read it. This is the *same* exposure the manual DevTools copy already has and
  RISK-046 already accepts — the extension mechanizes the copy (removing the DevTools
  fumble), it does not add a new exposure class. The cookie is Humble-only (no
  foragerr/OS credential), expires in weeks, and is invalidated by logging out of
  Humble (surfacing `expired`, FRG-SRC-005); no payment/billing action is reachable
  with it. The clipboard hop is intrinsic to any paste-based ingestion; removing it
  would require a native-messaging path, out of scope. RISK-046 updated to record this.
- **T-EXT-2 (self-distributed build integrity) — mitigated, RISK-050.** A tampered
  build could try to exceed its stated permissions or copy the cookie elsewhere.
  Controls: dependency-free deterministic build the operator rebuilds and byte-compares
  (FRG-EXT-003); AMO-signed Firefox artifact; MV3 no-remote-code guarantee; and a
  minimal, auditable manifest — `cookies` + `clipboardWrite` and a single
  `www.humblebundle.com` host permission, no `storage`, no content scripts, no
  `nativeMessaging`, no optional permissions, no CSP override, no other host
  (FRG-EXT-002). Any egress a tampered build added would therefore require a **visible
  source or manifest change** the operator sees on rebuild — that visibility, not the
  sandbox, is the control.
- **No-egress property — correctly attributed (gate correction, adversarial review).**
  The no-transmission guarantee is NOT "closed by construction because there is no
  network host permission": MV3 does **not** gate write-only egress on host
  permissions (a `fetch(..., {mode:"no-cors"})`, `sendBeacon`, `Image().src`,
  `WebSocket`, or `RTCPeerConnection` reaches any origin without one), and the default
  MV3 content-security policy restricts script/object sources but sets no `connect-src`.
  The property instead rests on three real controls: (1) the reviewed, reproducible
  source contains no egress primitive (a build-gate source scan is a tripwire for
  accidental regressions, explicitly not a proof against a determined obfuscated edit);
  (2) MV3 forbids remotely hosted code, so only the shipped, auditable bundle runs;
  (3) the minimal manifest keeps that auditable surface small and forbids the
  `nativeMessaging`/optional-permission/CSP-override keys a host permission would not
  have blocked. The shipped code today contains no egress path — nothing is broken;
  this note records the accurate basis for the claim.

Server-side surface unchanged: RISK-045 (cookie at rest), RISK-047 (store-JSON
parsing), RISK-048 (signed-URL egress) are untouched — no backend code changes in this
change. No new SOUP (dependency-free build).

### 2026-07-14 — site-regulated-story (0.9.x)

New surface: the repository's first GitHub Actions workflow
(`.github/workflows/pages.yml`) and a public static site on GitHub Pages.

- **The site is static output, not a listener** (no new COMP): five HTML pages +
  CSS + images generated by `site/build.py` from committed artifacts. No user
  input, no forms, no JavaScript, no cookies, no credentials, no backend — the
  application's own attack surface is unchanged. Spoofing/tampering of the
  *content* reduces to tampering with the repository or the deploy pipeline.
- **CI deploy pipeline** (supply chain, RISK-051): third-party actions are
  pinned to full commit SHAs; job token is least-privilege (`contents: read`,
  `pages: write`, `id-token: write`), so a compromised action cannot push to the
  repository; the build installs nothing and runs only stdlib Python over the
  checked-out tree. Pinning and permissions are enforced by tagged tests
  (FRG-SITE-005).
- **Information disclosure**: the site publishes only facts already public in
  the repository (registry, matrix, CHANGELOG, risk register) — rendering the
  risk register on the site discloses nothing the repo does not. The generator's
  banned-phrase scan (FRG-SITE-006) plus the generated-facts-only rule
  (FRG-SITE-001) prevent the site from *claiming* evidence that does not exist,
  which is this change's main integrity property.
- No new SOUP in the application; the four pinned workflow actions are recorded
  in the SOUP register's CI section.

### 2026-07-17 — m10-deployment-posture (M10 change 1)

Surface changed and its disposition (COMP 1 perimeter; first M10 change —
the hardening pass the pentest scope statement will cite via
`docs/security/posture.md`, the new posture authority this change adds):

- **Trusted-proxy handling exists** (FRG-SEC-007): the documented
  X-Forwarded-For refusal (COMP 1 / the rate limiter's S1 caveat) is
  DELIBERATELY revised — forwarded headers are now honored, but only when
  the request's direct peer is on the operator's explicit `trusted_proxies`
  allowlist (default empty = prior behavior, negative-tested). Resolution
  happens once at the perimeter by scope rewrite, so the session-cookie
  `Secure` flag, the FRG-NFR-014 rate-limiter key, and `auth.*` audit
  attribution can never disagree. This closes the
  Secure-cookie-never-set-behind-TLS-proxy gap. Misconfiguration risk
  recorded as RISK-052 (Spoofing; residual accepted as inherent).
- **Security response headers on every response** (FRG-SEC-006): nosniff,
  same-origin referrer policy, frame-ancestors denial, per-surface CSP
  (deny-all on data surfaces, self-only on the SPA with the recorded
  `style-src 'unsafe-inline'` loosening — posture.md §4). No CORS
  middleware exists, by tested position. Low new surface: one outermost
  pure-ASGI middleware, header-emission only.
- **Unauthenticated disclosure shrinks** (FRG-SEC-008, MODIFIED
  FRG-DEP-007): `/health` no longer reveals the DB path, migration
  revisions, scheduler task list, or error strings — overall status +
  failing component names only; the detail moved behind the perimeter
  (`/api/v1/system/health/components`). Unhandled errors are proven (by
  test) to return the generic envelope with no traceback; no debug flag
  exists. COMP 1's information-disclosure rows should be read with this
  narrowing.
- **Aged residuals decided**: RISK-008 formally re-accepted (dormant, no
  extraction path exists); FRG-DEP-012 diagnostic bundle re-accepted to
  backlog (posture.md §8). RISK-005's zipfile residual position restated
  unchanged.

No new STRIDE categories; no new SOUP; no new listener or credential. Net
effect is surface reduction plus one deliberate, allowlist-gated trust
revision (RISK-052).

### 2026-07-23 — fix-cover-proxy (0.9.x regression fix)

New attack surface and its disposition (COMP 1 / COMP 8 boundary):

- **Candidate-cover proxy exists** (FRG-META-021, `/api/v1/metadata/cover`):
  an authenticated endpoint fetching a CLIENT-SUPPLIED URL — the most
  SSRF-prone endpoint shape. Layered mitigations: default-deny perimeter
  (auth before any logic); HTTPS-only + ComicVine-media host allowlist with
  dot-boundary subdomain matching (lookalike suffixes tested); the fetch
  rides the hardened `external` egress profile (FRG-SEC-001 per-hop
  validation, TLS, bounded redirect walk, byte cap); response verified as a
  real image by magic bytes before a byte is served (an upstream HTML/JSON
  body can never reach the browser as an "image"); bounded in-memory LRU.
  Restores the candidate covers the v0.9.17 self-contained CSP blocked,
  WITHOUT widening the CSP — the FRG-SEC-006 posture is unchanged.
  Abuse scenarios are tagged tests (`backend/tests/security/test_cover_proxy.py`).

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
  - **G-5** CSRF stance + WebSocket Origin validation (CSWSH). **CLOSED (m8-auth-core,
    2026-07-12)**: FRG-SEC-005 implemented — Origin/Referer check on cookie-authenticated
    unsafe methods, API-key surface CSRF-immune by construction, WS Origin allowlist enforced
    pre-upgrade. RISK-022 Mitigated.
