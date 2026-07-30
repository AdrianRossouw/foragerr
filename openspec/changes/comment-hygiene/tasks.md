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
      of generic patterns — localhost/port literals, private-IP ranges,
      common container-name shapes, known home-directory path prefixes,
      review-provenance phrases ("fixed in review", "per gate feedback",
      etc.).
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

## 7. Verification

- [x] 7.1 Full test suite green; `tools/trace.py` picks up `FRG-PROC-023`
      via its tagged test(s).
- [x] 7.2 Manual impact confirmed as "none" (contributor-facing docs only,
      per the proposal's declaration) — no `docs/manual/` or `README.md`
      change required.
