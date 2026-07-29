# dev-process — comment-hygiene deltas

## ADDED Requirements

### Requirement: FRG-PROC-023 — Comment hygiene: deployment-neutral, provenance-free committed text

The following four rules SHALL govern all committed non-product text — code
comments, docstrings, test names and fixture literals, sample configs, and
committed docs outside the README/manual controlled documents already
governed by FRG-PROC-011, FRG-PROC-014, and FRG-PROC-018:

1. A comment SHALL state a constraint or invariant the code cannot express
   on its own. It SHALL NOT narrate what the following line does, and it
   SHALL NOT record provenance (e.g. "fixed in review", "per gate
   feedback") or otherwise reference the project's own review process.
   Citing a requirement ID in a comment is permitted only when the ID
   itself names the constraint being enforced (e.g. an invariant such as
   `FRG-SER-019`), not as a changelog-style footnote.
2. Committed text SHALL be deployment-neutral: it SHALL NOT contain a value
   true only of one environment — no test-rig hostnames or ports, no
   container names, no local filesystem paths, no operator usernames or
   email addresses, no session dates, and no provider account details.
3. Real-world identifiers used in examples SHALL be synthetic and neutral
   (e.g. "Example Series #1", `example.com`, `/comics`) and SHALL NEVER be
   a real collection or series title drawn from the operator's library.
4. Enforcement SHALL be two-layer: (a) every review gate's angle checklist
   includes a comment-hygiene pass, recorded in
   `docs/process/commit-standard.md` §Merge-gate checklist; and (b) a
   mechanical scanner `tools/comment_check.py` runs at every merge gate and
   SHALL exit 0 before a `--no-ff` merge to `main`.

- **Milestone**: — (process, not milestone-bound).
- **Source**: Owner feedback, raised twice during the M11 live-dogfood
  milestones (most recently at the M11 kickoff: "no review-process refs in
  code comments; no real collection titles in the public repo"); the
  repository is public.
- **Notes**: `tools/comment_check.py` follows the `tools/soup_check.py`
  precedent — a stdlib-only, gate-run script. Its design combines a
  committed set of generic patterns (localhost/port literals, private-IP
  ranges, common container-name shapes, known home-directory path
  prefixes, review-provenance phrases) with an optional **gitignored**
  local denylist file of operator-specific sensitive literals (real
  titles, rig hostnames); the tool warns but still exits 0 when that local
  file is absent, so the generic-pattern pass still runs in CI and other
  clones without requiring operator-private data to be committed anywhere
  — including inside the checker itself. This requirement governs
  contributor-facing committed text only; it does not alter
  user/administrator-facing behavior and carries no manual impact per
  FRG-PROC-011.

#### Scenario: A rig-specific value is committed

- **WHEN** a commit adds a code comment, docstring, test name, or sample
  config containing a test-rig hostname, port, container name, local
  filesystem path, operator username/email, session date, or provider
  account detail
- **THEN** `tools/comment_check.py` flags the value by its generic pattern
  match and exits non-zero, blocking the merge gate

#### Scenario: A comment narrates code or cites review provenance

- **WHEN** a review gate's comment-hygiene pass finds a comment that
  restates what the next line does, or records "fixed in review" / "per
  gate feedback" / another reference to the project's own review process,
  rather than stating a constraint the code cannot express
- **THEN** the gate flags it and the change does not merge until the
  comment is rewritten to state the invariant (or removed)

#### Scenario: A real collection title appears in example text

- **WHEN** committed text uses a real series/collection title from the
  operator's library as an example, rather than a synthetic identifier
  such as "Example Series #1"
- **THEN** the comment-hygiene gate pass flags it as a rule-3 violation

#### Scenario: The local denylist is absent

- **WHEN** `tools/comment_check.py` runs in an environment without the
  gitignored local denylist file (a fresh clone, CI)
- **THEN** it emits a warning that the local-denylist pass was skipped but
  still runs the generic-pattern pass and exits according to that pass's
  result — it does not fail solely because the local file is missing

#### Scenario: A requirement ID cited as the constraint is allowed

- **WHEN** a comment cites an `FRG-*` ID and the surrounding text states
  the invariant that ID names (e.g. "never suppress a single-issue wanted
  state — FRG-SER-019"), rather than referencing how or when the code was
  reviewed
- **THEN** the comment-hygiene pass accepts it as rule-1 compliant
