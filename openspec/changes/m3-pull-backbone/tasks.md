Work areas are partitioned by file ownership so each can run in its own worktree
(FRG-PROC-008), one writer per file area. Two shared wiring files —
`commands/__init__.py` (built-in task list) and the API router registration — are
touched by D and E respectively and are the only cross-area contention points; the
orchestrator owns those merges. Every requirement gets at least one tagged test
(FRG-PROC-004): pytest `@pytest.mark.req("FRG-...")`.

**Ordering / dependencies:** A defines the storage contract (`pull_entries` model +
repo) that B, C, and E code against, so A lands (or its model/repo interface is
frozen) first; B, C, E then proceed in parallel; D integrates them into the
`pull-refresh` command + schedule; F closes the gate. Subtle-vs-mechanical judgment
is called out per area so the orchestrator can assign model tiers accordingly.

## A. Backend — per-week storage model + repo + migration (FRG-PULL-003)

*Subtlety: MEDIUM — the idempotent replace-on-refresh transaction and deterministic
`entry_key` derivation are the correctness core; the schema itself is mechanical.*
Owns: `pull/models.py`, `pull/repo.py`, one alembic migration under `db/alembic`.

- [ ] A.1 `pull_entries` table + typed model (FRG-DB-008): `(week, entry_key)`
      unique, publisher/series_name/issue_number/cv_series_id/cv_issue_id/
      release_date/matched_issue_id (nullable FK to issues)/match_type/fetched_at.
      Forward migration under FRG-DB-002 (pre-migration backup is automatic,
      FRG-DB-003). Deterministic `entry_key` (prefer `cv_issue_id`, else normalized
      `(series_name, issue_number, publisher)`). Tagged tests: schema round-trips
      typed values; `entry_key` is stable for the same logical source row. [FRG-PULL-003]
- [ ] A.2 `repo.replace_week(week, entries)` — single-transaction delete-then-insert
      (FRG-DB-007) so a re-fetch is idempotent and a mid-run failure leaves the prior
      week intact. Tagged tests: re-fetch yields identical row counts/content; entries
      carry source CV IDs; a simulated failure mid-replace does not half-replace the
      week; a stored entry has a link + `match_type` but NO status field. [FRG-PULL-003]

## B. Backend — external pull-source fetch client (FRG-PULL-002)

*Subtlety: HIGH — trust posture, error-code mapping, degraded-health, and
untrusted-JSON handling are security-load-bearing.* Owns: `pull/source.py` and its
health-item contribution. Depends on A's typed entry model.

- [ ] B.1 Fetch client over the `security` **external** egress profile (FRG-SEC-001):
      configurable `pull_source_url`, current + previous week per run, mandatory
      timeouts (FRG-NFR-006), auto-redirect disabled. Tagged tests: a loopback/private
      source URL is refused per-hop (not fetched); timeouts enforced. [FRG-PULL-002]
- [ ] B.2 Untrusted-JSON parse (FRG-NFR-012): byte-capped stdlib parse into A's typed
      entry model; source-supplied CV IDs recorded as candidates only. Tagged tests: a
      malformed/oversized/hostile body degrades without raising and writes no partial
      week. [FRG-PULL-002]
- [ ] B.3 Documented error-code + outage handling: 619 skips the affected week
      (logged, other week still fetched); 522/666/transport failure → source-outage
      outcome that leaves the stored week intact and marks the pull source **degraded**
      in health (FRG-NFR-011 / FRG-API-014) with a remediation hint. Tagged tests: a
      522-equivalent leaves stored data intact + marks health degraded + view still
      renders (composed with A/E fixtures); a 619 skips only its week. [FRG-PULL-002]

## C. Backend — matching engine (FRG-PULL-004)

*Subtlety: HIGH — the guards (sequence delta, ±2-day window, book-type) are the
hard-won correctness core; this is where wrong matches are prevented.* Owns:
`pull/matching.py` (a thin adapter over `library/matching.py`). Depends on A's model.

- [ ] C.1 Id match first (CV series+issue) with a **book-type guard**; else guarded
      name match (normalized name/alias equal AND `0 ≤ seq delta < 3` AND release date
      within pull week ±2 days), reusing `library/matching.py` normalization. Resolve
      `match_type` (`id`/`name_seq`/`unmatched`/`new_series`) and persist link +
      type on the entry. Tagged tests: the mixed fixture (id match + valid name match +
      wrong-volume collision + unknown → exactly two links, two unmatched); book-type
      guard rejects a mismatched id; source IDs treated as candidates not authority. [FRG-PULL-004]
- [ ] C.2 New-series tagging: an unmatched `#1`/`#0` for a series not in the library is
      tagged `new_series` (a tag only — no series is created). Tagged test: new #1
      tagged, no series record created. [FRG-PULL-004]

## D. Backend — refresh trigger + scheduled/manual refresh command (FRG-PULL-005, FRG-PULL-006)

*Subtlety: MEDIUM — command orchestration, dedup, and throttle-vs-force semantics.*
Owns: `pull/commands.py`, new config keys on `config.py`, the built-in task entry in
`commands/__init__.py` (shared file — orchestrator merges). Depends on A, B, C.

- [ ] D.1 Refresh trigger (FRG-PULL-005): a matched-but-missing issue enqueues the
      existing `refresh-series` (`triggered_by="pull-refresh"`), deduplicated on the
      command queue (FRG-SCHED-003); the pull side writes no issue status. Tagged
      tests: missing matched issue → one deduplicated `refresh-series`, no status
      write; an already-present matched issue triggers none; post-refresh with policy
      "all" the issue is monitored/wanted via the normal path. [FRG-PULL-005]
- [ ] D.2 `pull-refresh` command (fetch → store → match → trigger) wiring A+B+C;
      register as a built-in recurring task (default 14400 s, min clamp ~3600 s) in
      `BUILTIN_SCHEDULED_TASKS`; internal re-poll throttle suppresses scheduled fetches
      but NOT a manual force-run; job runs recorded in history (FRG-SCHED-008) and
      pushed over WS (FRG-SCHED-010). New config keys `pull_enabled` (default off),
      `pull_source_url`, `pull_refresh_interval_seconds` (validated at startup,
      FRG-NFR-009; migrated FRG-DEP-004). Tagged tests: scheduled run at cadence
      observable in history; sub-minimum interval clamped; manual force-run within the
      throttle window still executes. [FRG-PULL-006]

## E. Backend/API — metadata-derived projection + weekly resource endpoint (FRG-PULL-001, FRG-API-019)

*Subtlety: MEDIUM — the derived-state projection over issue+queue records; the
endpoint itself is conventional.* Owns: `pull/projection.py`, `api/pull.py`, its
router registration (shared wiring — orchestrator merges). Depends on A's store.

- [ ] E.1 Weekly projection (FRG-PULL-001): for a target store-date week, the watched-
      series issues dated in that week with derived state (missing/wanted, downloading,
      downloaded, unmonitored) from issue+queue records (FRG-SER-004/FRG-DL-008);
      parameterised week (prev/current/next); functions with no/degraded source.
      Tagged tests: current-week content + derived state with no source; adjacent weeks
      by parameter; survives a degraded source. [FRG-PULL-001]
- [ ] E.2 `GET /api/v1/pull?week=` (FRG-API-019): standard paging envelope
      (FRG-API-006) + conventions (FRG-API-002); rows carry entry fields, `match_type`,
      linked issue id, derived state (or pending-refresh); omitted `week` → current
      week; no secret exposed; read-only (refresh is FRG-API-014 task force-run). Tagged
      tests: envelope + rows + derived state + no-secret; default week; read-only (no
      mutation) + force-run is the only refresh path. [FRG-API-019]

## F. Docs, security, traceability, gate

*Subtlety: security judgment (risk-row updates) is non-mechanical; the rest is
process.* Owns: `docs/`, registry, matrix.

- [ ] F.1 Manual (FRG-PROC-011): `docs/manual/admin/configuration.md` gains a "Weekly
      pull" subsection (source URL, refresh interval + clamp, `pull_enabled`, the
      degraded-source health item) and the scheduled-tasks list gains `pull-refresh`.
      No user-facing/README behavior change (the screen is change 2). [FRG-PROC-011]
- [ ] F.2 Security (FRG-PROC-006): `docs/security/threat-model.md` gains a STRIDE note
      on the pull fetch (untrusted-JSON ingress #5 + config-supplied outbound host);
      `docs/security/risk-register.md` **RISK-039** updated to implemented-status
      (timeouts, error-code handling, degraded-health, untrusted-JSON), and **RISK-025**
      pull-source arm closed via the external egress profile (FRG-SEC-001). No new risk
      id expected. If any dependency is added, update `docs/security/soup-register.md`
      in this same change and keep `tools/soup_check.py` at exit 0 (default: no SOUP
      change). [FRG-PROC-006, FRG-PROC-012]
- [ ] F.3 Registry + matrix: FRG-API-019 row already allocated at proposal time flips
      `proposed → implemented`; FRG-PULL-001..006 flip `approved → implemented`;
      traceability matrix regenerated; `tools/trace.py` exit 0. [FRG-PROC-004, FRG-PROC-005]
- [ ] F.4 Gate: backend suite green; pre-merge review cycle (`/code-review` +
      `/simplify`) + gate angles on the branch diff; fixes; archive the change;
      `--no-ff` merge with full suite green; post-merge SemVer tag per FRG-PROC-013. [FRG-PROC-007]
