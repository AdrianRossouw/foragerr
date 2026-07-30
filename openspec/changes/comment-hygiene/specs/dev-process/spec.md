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
  committed set of generic patterns with an optional **gitignored** local
  denylist file of operator-specific sensitive literals (real titles, rig
  hostnames, container names), one Python regex per line; the tool warns
  but still exits 0 when that local file is absent, so the generic-pattern
  pass still runs in CI and other clones without requiring
  operator-private data to be committed anywhere — including inside the
  checker itself.

  The **division of labour between the two enforcement layers is
  deliberate**: only some rule-2 values have a shape a pattern can
  recognise. The scanner's generic pass therefore covers host:port
  literals, private/CGNAT/link-local addresses, tailnet (`*.ts.net`)
  hostnames, home-directory and OS-user filesystem paths, email
  addresses, and review-provenance phrases. Container names, bare port
  numbers, session dates, provider account details and real-world titles
  are shapes that are legitimate almost everywhere — a date is a date, a
  name is a name — so patterning them would produce more false positives
  than findings; they are enforced by the gate's human/agent pass (rule 4a)
  and, where a specific literal is known, by the local denylist. Rules 1
  (narration) and 3 (real titles) are judgement calls for the same reason.

  This requirement governs contributor-facing committed text only; it does
  not alter user/administrator-facing behavior and carries no manual impact
  per FRG-PROC-011.

#### Scenario: A rig-specific value with a detectable shape is committed

- **WHEN** a commit adds a code comment, docstring, test name, or sample
  config containing a value from one of the mechanically detectable
  classes — a `host:port` literal (including `localhost` in any case,
  `[::1]`, or a `*.ts.net` peer) on any port other than the product's
  documented default, a private/CGNAT/link-local IP address, a bare
  tailnet hostname, a home-directory or OS-user filesystem path
  (`/Users/…`, `/home/…`, `/root/…`, `~/…`, `$HOME/…`, `C:\Users\…`), or a
  non-placeholder email address
- **THEN** `tools/comment_check.py` flags the value by its generic pattern
  match and exits non-zero, blocking the merge gate

#### Scenario: A rig-specific value with no detectable shape is committed

- **WHEN** a commit adds committed text containing an environment-specific
  value whose shape is indistinguishable from legitimate text — a
  container name, a bare port number, a session date, a provider account
  detail
- **THEN** the review gate's comment-hygiene pass (rule 4a) flags it as a
  rule-2 violation, and the scanner flags it only if the operator has
  added that literal to the local denylist — the scanner SHALL NOT carry a
  pattern whose false-positive rate would train authors to ignore it

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

#### Scenario: The local denylist covers text with no comment syntax

- **WHEN** the local denylist is present and a listed literal appears in a
  tracked text file the generic rules cannot parse for comments — a
  fixture corpus of release filenames, a JSON fixture, a site template
- **THEN** `tools/comment_check.py` flags it, because the denylist pass
  needs no comment extraction and SHALL run over the full text of every
  tracked text file; files it cannot decode SHALL be reported by count and
  name rather than silently dropped

#### Scenario: The local denylist is absent

- **WHEN** `tools/comment_check.py` runs in an environment without the
  gitignored local denylist file (a fresh clone, CI), or with one that
  holds no patterns
- **THEN** it emits a warning that the local-denylist pass was skipped but
  still runs the generic-pattern pass and exits according to that pass's
  result — it does not fail solely because the local file is missing

#### Scenario: The scanner cannot report clean when it did not scan

- **WHEN** `tools/comment_check.py` is invoked against a root that is not a
  directory, against a tree containing no text files, or with a malformed
  allowlist entry or an unparseable denylist line
- **THEN** it SHALL exit 2 with the reason on stderr rather than exit 0 —
  a gate whose failure mode is "reports clean" is worse than no gate

#### Scenario: A legitimate hit is declared for named rules only

- **WHEN** a committed exception is added to
  `tools/comment_check_allow.txt`
- **THEN** the entry SHALL enumerate the rule names it exempts; a
  wildcard, a missing rule name, or an unknown rule name is a
  configuration error (exit 2), because a blanket exemption also licenses
  every rule added after it was written; and an entry that suppresses
  nothing SHALL be reported as unused

#### Scenario: A requirement ID cited as the constraint is allowed

- **WHEN** a comment cites an `FRG-*` ID and the surrounding text states
  the invariant that ID names (e.g. "never suppress a single-issue wanted
  state — FRG-SER-019"), rather than referencing how or when the code was
  reviewed
- **THEN** the comment-hygiene pass accepts it as rule-1 compliant
