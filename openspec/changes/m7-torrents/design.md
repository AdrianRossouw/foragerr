# m7-torrents — seeding lifecycle & pack design (pre-designed 2026-07-11)

## Context

Verified against the codebase at design time (post-v0.5.5):

- `downloads/state.py`: **eight persisted `TrackedDownloadState` values**
  (downloading, import_blocked, import_pending, importing, imported,
  failed_pending, failed, ignored) with an explicit "the state vocabulary never
  changes again" contract, terminal-state set, and `_should_advance`
  anti-regression rules in `tracking.py`.
- `clients/base.py`: `ClientItemStatus` — six transient per-poll statuses
  (FRG-DL-001) — and the normalized `ClientItem` dataclass.
- `imports.py`: **move-based** import with crash recovery (id-tag adoption of
  moved-but-unrecorded files); client-entry removal only post-commit and only
  under `remove_completed_downloads`.
- `RemotePathMappingRow`, `BlocklistRow`, grab history, crash-safe queues
  (NFR-007) — all protocol-agnostic already.

**Core thesis: torrents add DATA and EXECUTORS, never new persisted states.**
The eight-state vocabulary survives untouched; everything torrent-specific
rides on the `ClientItem` protocol, per-download flags, and presentation.

## Goals / Non-Goals

**Goals:** seeding lifecycle with etiquette (never break a seed, never
hit-and-run); pack-native decisioning and import; Sonarr/Radarr-parity
failure semantics; zero regression to the usenet path.

**Non-Goals:** additional clients; non-Torznab discovery; foragerr-side
ratio accounting beyond the delegation backstop described below.

## Decisions

### 1. State machine: unchanged; seeding is an observation, not a state

`imported` stays terminal. A torrent's tracked row reaches `imported` exactly
like usenet; the difference is the **client item lives on**, still observed by
the poll loop. "Seeding" in the queue UI is a *presentation* derived from
(state == imported) ∧ (client item still present ∧ seeding). This preserves
the state-vocabulary contract, `_should_advance` logic, and every existing
test. Two new post-import concerns are handled by executors, not states:
removal (decision 5) and the seeding queue view (FRG-UI delta at impl).

### 2. `ClientItem` protocol extension (additive, defaulted)

New optional fields, defaulted so SABnzbd/DDL code is untouched:
`protocol: str = "usenet"`, `can_move_files: bool = True` (False while the
client still seeds the payload), `removable: bool = True` (client says seed
goals met / stopped), `seed_ratio: float | None`, `seeders: int | None`.
Mirrors Sonarr's `CanMoveFiles`/`CanBeRemoved` — proven shape for exactly
this problem.

### 3. Transmission status mapping (the classification table)

Transmission RPC `status` 0–6 + auxiliary fields → `ClientItemStatus`:

| Transmission observation | ClientItem |
|---|---|
| `metadataPercentComplete < 1` (magnet resolving) | QUEUED, message "fetching metadata" |
| download-wait (3) / check-wait (1) / checking (2) | QUEUED |
| downloading (4), progress moving | DOWNLOADING |
| downloading (4) ∧ `isStalled` | DOWNLOADING + **WARNING** message "stalled — no peers" |
| stopped (0) before complete (operator pause) | PAUSED |
| seeding (6) / seed-wait (5), goal not met | COMPLETED, `can_move_files=False`, `removable=False` |
| `isFinished` (goal met, stopped) | COMPLETED, `can_move_files=False`, `removable=True` |
| `error` = local error (3) | FAILED + errorString |
| `error` = tracker warn/error (1/2) | current status + **WARNING** (tracker errors are transient — Sonarr parity; never auto-fail on them) |

Hard failures are only local errors and explicit rejections; everything
tracker/peer-shaped is a warning. This is the fuzzy-failure decision encoded.

### 4. Stall semantics (owner: Sonarr/Radarr parity)

Stalled/metadata-stuck torrents surface as persistent queue warnings and roll
into health ("N downloads stalled"), exactly as visible as failures per the
UAT negative-paths rule — but nothing auto-fails by default. One-click
operator action on a stalled row: remove + blocklist (info-hash, TOR-006) +
re-search. A `stall_auto_fail_minutes` per-client knob exists and **ships
OFF** (never-surprise ethos); when enabled, the timeout transition uses the
existing failed_pending → failed → blocklist → re-search loop unchanged.

### 5. Seed-goal enforcement: delegate, verify, backstop

At add time foragerr sets per-torrent `seedRatioLimit`/`seedRatioMode=1` and
`seedIdleLimit` from per-client config (ratio, idle-minutes). Transmission
enforces; foragerr trusts `isFinished`/`removable`. The removal executor (runs
with the existing post-commit removal machinery): for rows imported ∧
removable ∧ `remove_completed_downloads` → remove torrent **and data** from
Transmission (data is foragerr's copy source, safe post-import; the library
copy is independent). **Etiquette invariants**: never remove before removable
even when `remove_completed_downloads` is on; never pause/stop a seeding
torrent as a side effect; blocklist-removal of a *seeding* torrent requires
the explicit operator action (it's the one legitimate seed-break, operator
owns it). Backstop: if per-torrent limit-setting fails (RPC rejects), a
warning marks the row "seed goals not delegated — client defaults apply";
foragerr never silently ratio-polices on its own.

### 6. Import-while-seeding: hardlink, else copy

When `can_move_files=False`, the import pipeline uses hardlink-if-same-device
else copy (new import mode alongside move; the mode is a per-download fact,
not config). Crash recovery: the existing id-tag adoption already tolerates
source-still-present (copy semantics make the source persisting *normal*);
add the inverse guard — target-exists-with-tag → adopt, never re-copy.
Usenet/DDL keep move semantics unchanged.

### 7. Grab side

Server-side `.torrent` fetch (indexer auth stays server-side, mirrors NZB
addfile): **bencode parse is untrusted input** — size-capped, no recursion
bombs, STRIDE row at impl; SOUP decision then (a vetted small bencode lib vs
~60-line vendored parser — lean lib, decide on review). Info-hash = SHA-1 of
the info dict, the tracking join key (TOR-003); magnets pass through with
hash parsed from the URI. Torznab (IDX-012) reuses the Newznab client shape +
`seeders`/`peers`/`infohash` attrs feeding TOR-005's min-seeders gate and
log-bucketed peers comparator, inserted protocol-conditionally into the
existing chain after indexer priority. Announce URLs and Torznab keys carry
private-tracker passkeys: SecretStr + keystore + redaction, never logged.

### 8. Packs (owner: in scope, weekly-pull emphasis)

**Classification** at release evaluation: `single` / `run-pack`
("#1–50", "Complete", "v1-v10" patterns) / `weekly-pack` (date-shaped titles,
"weekly pack" markers). Heuristics tuned on Torznab fixtures at impl.

**Decisioning**: a pack is grabbable when it covers ≥1 wanted issue —
run-packs match series+range against wanted; weekly-packs match the PULL
week's wanted entries (this is the "find the weekly torrent from the pull
list" feature: the pull-refresh can trigger a weekly-pack search for weeks
with wanted issues). Value scoring prefers the release filling the most
wanted issues per grab; one grab claims *all* covered wanted issues (no
duplicate per-issue grabs for the same pack — the dispatch marks them all
pending against one download id).

**Import (1→N)**: on completion, every file in the payload runs through the
existing filename parser → issue matching; **only monitored/wanted issues
import** (hardlink/copy makes selective import free — unimported files simply
keep seeding, nothing is deleted); junk and unmatched files are logged and
visible on the tracked row, never errors. Per-file import results attach to
the one tracked download (N imported, M skipped, K unmatched); the row
reaches `imported` when every *matched-wanted* file has imported, and
per-file failures use the existing manual-import surface scoped to that
download. Partial pack utility is the norm (a weekly pack where you want 4
issues), not an edge case.

## Risks / Trade-offs

- [Seeding retention grows disk] → data removed at goal-met removal; manual
  guidance on seed-dir sizing; packs amplify this — noted prominently.
- [Cross-device hardlink degrades to copy = 2× disk during seed] → same-device
  layout guidance in manual (client download dir on the library volume).
- [Bencode parser on hostile input] → caps + STRIDE + fuzz-shaped tests.
- [Private-tracker etiquette violations] → the decision-5 invariants are
  spec-level requirements at impl, each with a tagged test.
- [Transmission RPC drift/versions] → `test()` probes RPC version; client
  isolated behind the existing protocol like SABnzbd.
- [Weekly-pack title heuristics misfire] → classification is advisory; a
  misclassified pack still imports correctly via 1→N matching (classification
  only affects *search/decisioning*, never import correctness).

## Migration Plan

One migration at impl: torrent client rows (settings via keystore),
`tracked_downloads` gains protocol/info-hash/seeding-observation columns —
**no state-vocabulary change**. Usenet path untouched (regression suite must
prove it: same grabs, same transitions, same imports).

## Open Questions

- Bencode dependency vs vendored parser — SOUP decision at m7-torznab-grab
  review.
- Whether weekly-pull-pack search (change 4) folds into packs (change 3) —
  sized at M7 kickoff.
- Pack classification heuristics — tuned against real Torznab fixtures then.
