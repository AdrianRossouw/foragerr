# comment-hygiene — tasks

## 1. Registry (FRG-PROC-002)

- [x] 1.1 Allocate `FRG-PROC-023` in
      `docs/traceability/requirements-registry.md` (status `proposed`,
      milestone `—`), done at proposal time — this task is complete as of
      this proposal's commit.

## 2. Standard doc (FRG-PROC-023)

- [x] 2.1 Write `docs/process/code-comments.md`: the four rules in full,
      each with a compliant/non-compliant example pair (comment
      narration vs. invariant; rig hostname vs. neutral placeholder; real
      collection title vs. "Example Series #1"; review-provenance phrase
      vs. requirement-ID-as-constraint).
- [x] 2.2 Cross-link from `docs/process/commit-standard.md` and from
      `CLAUDE.md`.

## 3. Merge-gate checklist (FRG-PROC-023)

- [x] 3.1 Add a comment-hygiene line to
      `docs/process/commit-standard.md` §Merge-gate checklist, alongside
      the existing SOUP/trace/risk-register mechanical-check lines,
      naming `tools/comment_check.py` and the gate's angle-checklist pass.

## 4. CLAUDE.md pointer (FRG-PROC-023)

- [x] 4.1 Add one line under "Non-negotiable process rules" pointing to
      `docs/process/code-comments.md`, matching the existing style used
      for FRG-PROC-004/006 summaries.

## 5. Mechanical scanner (FRG-PROC-023)

- [x] 5.1 `tools/comment_check.py`: stdlib-only script (no new
      dependency — `tools/soup_check.py` precedent) that walks committed
      text (comments, docstrings, test names/fixture literals, sample
      configs, committed docs outside README/manual) for a committed set
      of generic patterns — host:port literals, private/CGNAT/link-local
      IP ranges, tailnet hostnames, home-directory and OS-user path
      shapes, email addresses, review-provenance phrases ("fixed in
      review", "per gate feedback", etc.). Container names and session
      dates are deliberately excluded (task 7.2).
- [x] 5.2 Optional gitignored local denylist file support: if present,
      also flags its literal entries (real titles, rig hostnames the
      operator maintains locally); if absent, emits a warning and still
      exits according to the generic-pattern pass alone (never fails
      solely because the local file is missing).
- [x] 5.3 Exits non-zero on any generic-pattern or local-denylist match,
      naming the file/line and the matched rule, mirroring
      `tools/soup_check.py`'s reporting style.
- [x] 5.4 Tagged test(s) for FRG-PROC-023 covering: a rig-hostname/port
      literal is flagged; a review-provenance phrase is flagged; a clean
      fixture tree passes; the local-denylist-absent case still exits 0
      when the generic pass is clean.
- [x] 5.5 Wire into the merge-gate checklist procedure (this is the
      mechanical half of task 3; task 3 documents it, this task makes it
      real and runnable).

## 6. Retroactive sweep (FRG-PROC-023)

- [x] 6.1 Run `tools/comment_check.py` (once 5.x lands) against the full
      committed tree; fix every flagged comment/docstring/test
      name/fixture literal/sample config to comply with the four rules
      (text-only changes, no behavior change).
- [x] 6.2 Confirm `tools/comment_check.py` exits 0 against the swept tree
      and stays green alongside the rest of the merge-gate checklist
      (`tools/trace.py`, `tools/soup_check.py`,
      `tools/risk_register_check.py`).

## 7. Gate hardening (FRG-PROC-023)

- [x] 7.1 Quote parity: quote state no longer survives a newline in the
      `#`/`//` extractor, so one unbalanced quote (a TOML `'''`
      delimiter, a JS regex literal, a JSX apostrophe, a shell heredoc
      body) can no longer blind the scanner to every later comment in the
      file; a line that both leaves a quote open and holds a comment
      marker inside it is reported as a misparse. Regression fixture per
      breaker shape.
- [x] 7.2 Detection/spec alignment: added case-insensitive hosts, `[::1]`
      loopback, CGNAT `100.64/10` and link-local `169.254/16`, `*.ts.net`
      hostnames, case-insensitive `C:\Users\`, and `~/` / `$HOME/` /
      `/root/` home-directory shapes; narrowed the requirement's scenario
      wording and `docs/process/code-comments.md` to state honestly which
      classes are mechanical and which belong to the gate pass.
- [x] 7.3 Mutation resistance: one pinning fixture per rule with an exact
      `rules_hit` assertion, plus a test asserting every rule in `RULES`
      is pinned.
- [x] 7.4 Local-denylist pass runs over every tracked text file (it needs
      no comment extraction), so fixture corpora, JSON fixtures and site
      templates are covered; undecodable files are counted and named.
- [x] 7.5 Allowlist tightened: rule names enumerated (wildcard, missing
      and unknown names are configuration errors), unused entries
      reported, and each committed entry narrowed to its measured rule
      set.
- [x] 7.6 Fail closed: a root that is not a directory, a tree with no text
      files, a malformed allowlist entry and an unparseable denylist line
      all exit 2; the non-git fallback walk skips tool and agent-state
      directories.
- [x] 7.7 Denylist ergonomics: an empty file counts as absent, the notice
      goes to stderr, `--denylist` / `FORAGERR_COMMENT_DENYLIST` point at
      a shared file, and each line is documented as a Python regex
      (unparseable = configuration error, not a silent substring
      fallback).

## 8. Verification

- [x] 8.1 Full test suite green; `tools/trace.py` picks up `FRG-PROC-023`
      via its tagged test(s).
- [x] 8.2 Manual impact confirmed as "none" (contributor-facing docs only,
      per the proposal's declaration) — no `docs/manual/` or `README.md`
      change required.
