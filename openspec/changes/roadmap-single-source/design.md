# Design — roadmap-single-source

## Context

Forward-looking text is currently duplicated: `README.md` carries a five-item
Roadmap section (M4–M8), and `docs/manual/` restates future milestones inline
(`admin/network.md`: "no auth before M8"). These passages rot silently — the
README still described the M4 design refresh as unshipped after v0.4.2/v0.4.3
delivered most of it. FRG-PROC-014's checks catch the inverse error only
(unshipped work advertised as shipped). The repo already has a working pattern
for mechanical text governance: `backend/tests/test_public_labelling.py` scans
committed documents at every merge gate (FRG-PROC-014/011), and
`tools/trace.py` already parses `docs/traceability/requirements-registry.md`.
This CAPA composes those two existing mechanisms; it introduces no new
machinery.

## Goals / Non-Goals

**Goals:**

- One home for forward-looking content: `docs/roadmap.md`.
- Corrective sweep of README + manual; fix the stale M4 entry.
- Merge-gate containment + freshness checks (FRG-PROC-018), test-tagged.

**Non-Goals:**

- No general doc-consistency framework (recorded observation; generalize only
  on a second instance, via its own proposal).
- No versioning/release-process changes; no renumbering.
- No scanning of non-controlled artifacts (archived proposals, `docs/research/`,
  `docs/process/` history) — controlled scope is `README.md`, `docs/manual/**`,
  `docs/roadmap.md`.

## Decisions

1. **`docs/roadmap.md` as a plain controlled markdown doc, one entry per
   planned item: milestone, short description, `FRG-*` ids where allocated.**
   Alternative considered: deriving the roadmap from the registry
   (status ≠ implemented → roadmap). Rejected: the registry lacks narrative
   (why an item matters, sequencing), and most future items have no allocated
   ids yet (ids are allocated at proposal time per FRG-PROC-002 lesson).
   Instead the doc is hand-written and *validated against* the registry.

2. **New test module `backend/tests/test_roadmap_consistency.py`, tagged
   `@pytest.mark.req("FRG-PROC-018")`,** following the
   `test_public_labelling.py` pattern (walk committed files, assert on text),
   rather than a standalone `tools/` script. Rationale: merge gates already run
   pytest; a script would need separate wiring into the gate checklist and can
   be forgotten — the exact failure mode this CAPA addresses. Registry parsing
   reuses/adapts the row-parsing approach in `tools/trace.py`.

3. **Containment check = token scan with a file+token allowlist.**
   Scanned set: `README.md`, `docs/manual/**/*.md`. Signals: future-milestone
   tokens (`M5`–`M9` as standalone tokens — see risk below on `M4`) and a small
   planned-phrasing marker list ("planned", "not yet shipped", "upcoming",
   "future work", "will arrive"). Allowlist is a literal structure in the test
   module: `(relative_path, token)` pairs, each with a comment justifying it.
   Alternative (semantic/LLM review) rejected: not mechanical, not
   merge-gate-stable.

4. **Freshness check = parse `docs/roadmap.md` for `FRG-*` ids, join against
   registry status.** Any id in the roadmap with `implemented` status fails
   with a message naming the id and the roadmap line. Ids with `approved` or
   `active` status pass. Unknown ids also fail (typo guard — consistent with
   PROC-014's resolving-links posture).

5. **README keeps its Roadmap heading** (PROC-014 requires it and
   `test_public_labelling.py` asserts on it) but its body becomes one or two
   sentences plus a link to `docs/roadmap.md`. The "Humble importer and archive
   import listed as future work" assertion in the labelling test retargets to
   `docs/roadmap.md`.

6. **Milestone-token edge: M4 is in progress, not future.** The containment
   token set is `M5`–`M9` plus phrasing markers; `M4` references in controlled
   docs are handled by the corrective sweep (removed or moved to the roadmap),
   not by the scanner, so the check doesn't churn every time the current
   milestone increments. When M5 becomes current, the shipping change that
   makes it current updates the token set — a one-line, gate-visible edit.

## Risks / Trade-offs

- [False positives: "M5" etc. appearing in prose with another meaning, or in
  code snippets inside the manual] → word-boundary regex, scan scope limited to
  controlled docs, explicit allowlist for legitimate cases; failure message
  names file+token so triage is immediate.
- [False negatives: forward-looking prose that uses none of the marker
  phrases] → accepted; the freshness check catches the highest-damage case
  (shipped-but-still-advertised-as-future) regardless of phrasing, and the
  containment list can grow when a miss is observed.
- [Allowlist rot: exceptions accumulate] → each entry requires an inline
  justification comment; reviewers see additions in the diff at the gate.
- [Roadmap doc itself goes stale for items without FRG ids] → freshness can
  only validate cited ids; narrative-only entries still rely on humans. Partial
  mitigation is FRG-PROC-011's manual-impact declaration now having exactly one
  place to consider.

## Migration Plan

Single change on `process/roadmap-single-source`: registry row + spec delta +
`docs/roadmap.md` + corrective sweep + test module land together; merge gate
runs the new tests. No data or deployment migration. Rollback = revert the
merge commit (docs and tests only, no runtime surface).

## Open Questions

- Exact allowlist contents fall out of the sweep (expected: zero-to-few
  entries, e.g. `CHANGELOG.md` is out of scope, `docs/manual/admin/network.md`
  gets a link instead of an exception).
