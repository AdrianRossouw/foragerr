# roadmap-single-source

## Why

Forward-looking roadmap text is duplicated across long-lived documents and goes
stale by default: the `README.md` Roadmap section still lists the M4 design
refresh as "planned, not yet shipped" although its chapters have been landing
since v0.4.2, and `docs/manual/` restates future milestones inline (e.g.
`admin/network.md`'s "no auth before M8"). Nothing edits these passages when a
roadmap item ships — staleness arrives through the passage of time, not through
any diff a merge gate can inspect. FRG-PROC-014 already forbids the inverse
error (advertising unshipped work as shipped) but has no check for shipped work
still advertised as future. This is a process CAPA: correct the stale documents
now, and make roadmap staleness mechanically detectable at every merge gate.

## What Changes

- **New controlled document `docs/roadmap.md`** — the single home for
  forward-looking content (unshipped milestones, planned features). It lists
  each planned item with its milestone and, where allocated, its `FRG-*` ids.
- **Corrective sweep**: `README.md`'s Roadmap section shrinks to a short
  pointer at `docs/roadmap.md` (keeping the Roadmap heading FRG-PROC-014
  expects); the stale M4 "design refresh" entry is corrected (shipped chapters
  out, remaining pull-screen work stays); `docs/manual/` forward references are
  replaced with links to the roadmap document.
- **Preventive checks** (merge-gate tests, same committed-text-scanning pattern
  as `backend/tests/test_public_labelling.py`):
  1. **Containment** — future-milestone tokens and planned-phrasing markers may
     not appear in committed docs outside `docs/roadmap.md`, minus a small
     explicit allowlist.
  2. **Freshness** — any `FRG-*` id `docs/roadmap.md` presents as planned must
     not have `implemented` status in `docs/traceability/requirements-registry.md`;
     shipping an item forces the roadmap edit in the same change or the suite
     goes red.
- **New requirement `FRG-PROC-018`** (allocated in the registry at proposal
  time) stating the narrow single-source rule: forward-looking content lives
  only in `docs/roadmap.md`; other controlled documents link, never restate.
- **Amendment to `FRG-PROC-014`**: the README Roadmap heading now points at
  `docs/roadmap.md`; the "Humble importer and archive import listed as future
  work" obligation moves to the roadmap document.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `dev-process`: new requirement FRG-PROC-018 (roadmap single source of truth +
  containment/freshness checks); FRG-PROC-014 amended so the README Roadmap
  section is a pointer and the future-work listing obligation transfers to
  `docs/roadmap.md`.

## Non-goals

- **No general documentation-consistency framework.** The general case exists —
  any committed doc asserting a fact whose truth lives elsewhere can rot — but
  this change deliberately solves only the roadmap instance. If a second
  instance of the pattern appears, generalizing becomes its own proposal. This
  observation is recorded here so it isn't lost.
- No change to versioning or release-tagging practice (FRG-PROC-013 untouched);
  no renumbering of anything.
- No restructuring of the manual beyond replacing forward-looking restatements
  with links.
- No retroactive editing of archived proposals or research docs; the
  containment check scopes to controlled documents (`README.md`,
  `docs/manual/`, `docs/roadmap.md`), not historical artifacts.

## Impact

- **Documents**: `README.md` (Roadmap section), new `docs/roadmap.md`,
  `docs/manual/admin/network.md` (and any other forward references the sweep
  finds), `docs/traceability/requirements-registry.md` (FRG-PROC-018 row).
- **Specs**: `openspec/specs/dev-process/spec.md` via delta (FRG-PROC-018 new,
  FRG-PROC-014 amended).
- **Tests**: new merge-gate test module (pytest, `@pytest.mark.req("FRG-PROC-018")`)
  for containment + freshness; existing `test_public_labelling.py` expectations
  for the README Roadmap heading adjusted if needed.
- **Manual impact** (FRG-PROC-011): `docs/manual/` touched only where forward
  references become links; README updated as described. No user/admin-facing
  application behavior changes.
- **Security impact**: none — no new attack surface, no dependencies added
  (`docs/security/` and SOUP register untouched).

## Approval

Approved by Adrian, 2026-07-10 ("i'm happy with it"), in-session per
FRG-PROC-009. Scope as proposed: containment scan limited to `README.md` +
`docs/manual/**`; general doc-consistency framework explicitly out of scope.
