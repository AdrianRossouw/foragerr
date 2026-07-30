# read-only-library — index and serve an existing collection without touching it

## Why

Rig finding #4 (validated by real use): the owner pointed foragerr at his
real, already-organized comics folder — read-only mounted — and it was
refused, because a library root must be writable. foragerr's library is
built to *manage* files (rename to canonical names, move into per-series
folders, download missing issues into the root), so a read-only mount has
nothing it can write and is rejected. But the want is real and different:
**read and serve an existing collection as-is** — recognize its series and
issues, cache metadata, and serve it over OPDS to the iPad — without
foragerr reorganizing, renaming, moving, or acquiring anything.

Two payoffs beyond the feature itself: it lets the operator actually *run*
foragerr against a real multi-thousand-issue library today (not rig
fixtures), and that is the first look at how import, matching, and the UI
behave **at real scale** — the same live-use signal that has produced
every substantive finding so far.

Terminology note: foragerr's "Sources" already means account-backed store
inventory (Humble). This is a **read-only library root** ("reference
library"), a distinct concept from a store source — named so it does not
collide with the store machinery.

## What Changes

- **Read-only library root** (new `FRG-SER-021`): a root may be registered
  **read-only** — the writability check is bypassed for it, and every disk
  write path (import rename/move, per-series rescan moves, download-into,
  delete/recycle-bin) is **refused, fail-closed**, for any series whose
  root is read-only. A read-only root's registration instead requires the
  path be an existing, *readable* directory.
- **Index-in-place import** (new `FRG-IMP-028`): importing a group under a
  read-only root registers the series and its `issue_files` pointing at the
  files' **existing paths**, with **no rename, move, or copy** — the disk
  is never mutated. Matching, metadata fetch (to the DB), and cover caching
  (to the config dir, never the root) work as normal.
- **Read-only series are browse/serve-only** (new `FRG-SER-022`): a series
  on a read-only root is never monitored, wanted, searched, or acquired
  (there is nowhere to download into), and its files are never moved or
  deleted. It refreshes metadata and serves over OPDS exactly like any
  other series. Any attempt to monitor/search/grab/delete-files such a
  series is refused with a clear reason.
- **Read-only treatment in the UI** (new `FRG-UI-045`): read-only roots and
  their series are marked read-only; the monitor toggle, "search", and
  file-mutating actions are hidden or disabled for them, so the operator
  is never offered an action the backend will refuse. OPDS/reading is
  unaffected.

## Capabilities

### New Capabilities

None — extensions of the existing library/import/OPDS areas.

### Modified Capabilities

- `ser`: ADDED FRG-SER-021 (read-only root), FRG-SER-022 (browse-only
  series). MODIFIED FRG-SER-008 (root registration/writability) — the
  writable requirement becomes "writable OR read-only-and-readable".
- `imp`: ADDED FRG-IMP-028 (index-in-place import, no disk mutation).
- `ui`: ADDED FRG-UI-045 (read-only marking + suppressed write actions).

## Impact

- Backend: root-folder model + `create_root_folder` (a `read_only` flag,
  registration validation bypasses W_OK and requires R_OK);
  `library/flows/library_import.py` (index-in-place mode — no rename/move
  under a RO root); `library/flows/rescan.py` (read-only walk only, never
  moves); the download/import write paths + recycle-bin delete (refuse for
  RO series); monitoring / wanted / search / grab entry points (refuse or
  no-op for RO series); `api/library_config.py` (RO registration).
- Frontend: root-folder add form (read-only checkbox), series/library
  read-only marking, suppressed monitor/search/delete affordances.
- **Safety (FRG-PROC-006): this is a fail-closed write-boundary feature.**
  Every disk-write path must honor read-only or it either errors against
  the mount or, worse, mutates the very files the feature protects. The
  gate is a full audit of write paths with tests that ASSERT no write
  occurs under a read-only root across import, rescan, download, and
  delete. No new listener/egress/parser of untrusted input; no new
  dependency; no migration beyond the additive `read_only` column.
- Manual: `docs/manual/user/library.md` + `import.md` (registering a
  read-only library; what it does and does not do); `docs/manual/admin/
  configuration.md` §Root folders (previously said read-only mounts were
  unsupported — a gate review caught this as a direct contradiction the
  original manual-impact declaration missed); `docs/manual/user/web-ui.md`
  (Media Management's read-only checkbox/badge, Add Series inline
  registration wording); `docs/manual/user/import.md` §Upgrades,
  deletions, and the recycle bin plus the two disposal rows in
  `configuration.md` (a recycle bin / duplicate dump inside a read-only
  root is rejected on save and refused at use, and reported in health).

## Non-goals

- Acquisition into a read-only library, or "complete this RO series into a
  separate writable root" — a read-only series is browse-only, full stop.
- Multiple/blended read-only+writable behavior on one root.
- The rest of the parked import-heuristics pre-design (segmentation,
  flat-folder placement) — independent future work.
- OPDS metadata-facet browsing (a separate banked idea).

## Approval

**Approved by Adrian, 2026-07-29** ("i approve all the active proposals"). Discussed with the owner 2026-07-29 (agreed: the **minimal** shape —
index + serve, no acquisition — and pulling it forward to run foragerr on
the real library now, accepting a small 1.0-timeline cost for the
at-scale dogfood signal). Sequenced AFTER the approved import-atomicity
fix (whose write-path audit this feature builds on).

## Gate evidence

Tier: full (write boundary + acquisition boundary = security-touching). Angles:
adversarial write-boundary, threat-model/STRIDE, backend correctness, test
non-vacuity, frontend contract, process audit, simplify, migration/DB, plus
Codex full-diff and an independent verification of the security docs' coverage
claim against the shipped code.

Verdict fix-first. Eleven reachable bypasses found and closed across three fix
rounds: in-place disposal reaching the operator's originals (default recycle
path empty, so os.remove — format-twin groups made the destructive ordering the
natural one), post-placement ComicInfo/CBR-CBZ rewrites, unguarded on-demand
convert commands, boundary keyed on the root FK while paths validated against
any root, manual import moving files out of a read-only library, rescan
path_override walking it, acquisition via generic command enqueue, source
entitlement match/grab, and disposal directories resolving inside a read-only
root (config-time check bypassable by ordering or by env/config.json).

Structural outcomes rather than per-endpoint patches: the boundary derives from
the root flag OR the resolved path's containment; one hoisted chokepoint in
pipeline.execute covering both branches plus move-mode source confinement;
add/edit confine a supplied path to the assigned root; two registry-level
invariant tests (file-mutating commands, acquiring commands) that fail until a
new command is triaged, plus an enumeration test over the disposal primitives.
Non-vacuity proven by neutering each guard: 20/20 then 8/8 failed their tests.
Two guards found genuinely redundant were deleted rather than kept unprovable.

Suites at merge: backend 2788, frontend 568, tsc clean, e2e GREEN 42/0/1
(includes an in-container zero-write proof: the read-only root is mounted
writable and renaming is enabled, so an unchanged listing is a refusal rather
than an inability to write). comment_check / soup_check / risk_register_check /
trace all exit 0.

Documented residuals: rescan path_override general confinement deferred (would
renegotiate FRG-SER-010, whose scenario passes a path outside every registered
root) — recorded on RISK-019; a disposal directory supplied outside the API is
caught at use rather than at load, with the health surface as the only pre-use
signal — recorded on RISK-054; grab refusal, rescan moves, archive rewrites and
disposal refusals are backend-tested only, stated as e2e coverage limits rather
than implied by a green verdict.
