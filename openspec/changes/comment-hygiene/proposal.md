# comment-hygiene — deployment-neutral, provenance-free committed text

## Why

foragerr's source is public. Twice during the live-dogfood milestones,
values and phrasing that only make sense on Adrian's own test rig or in the
project's own review process drifted into committed text — a comment citing
a real collection title from the operator's library, a docstring or test
name naming a rig-specific host/port/container, a code comment recording
"fixed in review" or citing a gate finding instead of stating the invariant
the fix protects. Adrian has raised this twice as standing feedback (most
recently at the M11 kickoff: "no review-process refs in code comments; no
real collection titles in the public repo"). The pattern repeats because
there is currently no committed standard defining what a comment/docstring/
test-name/sample-config is *for*, no checklist line at the review gate that
names this class of defect, and no mechanical check — every prior fix has
been a one-off cleanup rather than a durable close.

This proposal is process-only: it defines the standard and the two
enforcement layers (gate checklist item + mechanical scanner). It does not
implement the scanner or perform the retroactive sweep — those are
tasks for the approved change to execute.

## What Changes

- **New requirement `FRG-PROC-023`** (dev-process): a comment-hygiene
  standard covering all committed non-product text — code comments,
  docstrings, test names and fixture literals, sample configs, and
  committed docs (not README/manual controlled-document content, which
  FRG-PROC-011/014/018 already govern for their own facts). Four rules:
  1. A comment states a constraint or invariant the code cannot express
     on its own — never narration of what the next line does, never
     provenance ("fixed in review", "per gate feedback"), never a
     reference to the project's own review process. Citing a requirement
     ID is allowed only when the ID *is* the constraint (an invariant
     like `FRG-SER-019`), not as a change-log footnote.
  2. Deployment-neutrality: no value true only of one environment — no
     test-rig hostnames/ports/container names, no local filesystem paths,
     no operator usernames or emails, no session dates, no provider
     account details.
  3. Real-world identifiers used in examples are synthetic and neutral
     ("Example Series #1", `example.com`, `/comics`) — never a real
     collection/series title from the operator's library.
  4. Two-layer enforcement: every review gate's angle checklist includes
     a comment-hygiene pass (`docs/process/commit-standard.md` §Merge-gate
     checklist), and a mechanical scanner `tools/comment_check.py` (same
     precedent as `tools/soup_check.py`) runs at every merge gate and must
     exit 0.
- New standard doc `docs/process/code-comments.md` spelling out the four
  rules with examples (good/bad pairs), referenced from the commit
  standard and from `CLAUDE.md`.
- `docs/process/commit-standard.md` §Merge-gate checklist gains a
  comment-hygiene line alongside the existing SOUP/trace/risk-register
  mechanical checks.
- `CLAUDE.md` gets a one-line pointer to the new standard under
  "Non-negotiable process rules", consistent with how FRG-PROC-004/006 are
  already summarized there.
- `tools/comment_check.py` (implementation task, not drafted here): scans
  committed text for a committed set of generic patterns (localhost/PORT
  literals, private-IP ranges, common container-name shapes, filesystem
  paths under known home-directory prefixes, review-provenance phrases
  like "per review"/"gate feedback"/"fixed in review") plus, optionally, a
  **gitignored local denylist file** of sensitive literals (real titles,
  hostnames) that the operator maintains locally — the tool warns but still
  exits 0 when that local file is absent, so CI and other clones keep
  running the generic-pattern pass without needing operator-private data
  committed anywhere, including inside the checker itself.
- Retroactive sweep of existing committed comments/docstrings/test
  names/sample configs against the new standard, as the final task of the
  approved change (separate from — and gated by passing —
  `tools/comment_check.py` once it exists).

## Capabilities

### New Capabilities

None — this extends the existing `dev-process` capability.

### Modified Capabilities

- `dev-process`: ADDED `FRG-PROC-023` (comment hygiene: deployment-neutral,
  provenance-free committed text).

## Impact

- Docs: `docs/process/code-comments.md` (new), `docs/process/commit-standard.md`
  (checklist line), `CLAUDE.md` (one-line pointer),
  `docs/traceability/requirements-registry.md` (this proposal's registry
  edit, done now per FRG-PROC-002).
- Code (implementation phase, post-approval): `tools/comment_check.py` +
  its tagged test; a retroactive sweep touching comments/docstrings/test
  names/sample configs across `backend/` and `frontend/` (no behavioral
  change — text only).
- No new runtime dependency (the scanner is stdlib-only per the SOUP
  precedent of `tools/soup_check.py`/`tools/trace.py`); no new attack
  surface (a local static-text scanner, not a listener or parser of
  untrusted input) — no `docs/security/` update required.
- Manual impact: **none.** `docs/manual/` documents user/administrator-facing
  application behavior; this requirement governs contributor-facing
  committed text only and changes nothing an operator sees or configures.
  Contributor-facing documentation lives in `docs/process/` and is updated
  by this change itself.

## Non-goals

- Rewriting README/manual prose facts — those already have their own
  governing requirements (FRG-PROC-011, FRG-PROC-014, FRG-PROC-018) and
  their own mechanical checks; this proposal's scope is comments,
  docstrings, test names, fixture literals, sample configs, and other
  committed docs outside those controlled documents.
- Building `tools/comment_check.py` or performing the retroactive sweep —
  drafted as tasks for the approved change, not implemented by this
  proposal.
- A general secret scanner — that is FRG-PROC-015 (gitleaks) and stays
  separate; comment hygiene is about neutrality and provenance, not
  credential leakage.

## Approval


Approved by Adrian, 2026-07-29 (in-session): "i approve the comment hygiene",
with two directives folded into scope: (1) run the retroactive sweep over
existing comments as part of this change, (2) keep `tools/comment_check.py`
generic — pattern-class detectors (host:port literals, personal absolute
paths, provenance phrasing, email addresses), not a list of specific values.
