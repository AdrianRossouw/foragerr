# Living-documents process review — 2026-07-13

**Trigger.** The owner attempted a routine follow-up against the security risk
register — "were the auth risks resolved?" — and could not answer it from the
document: the relevant row buried its current state at the tail of a ~4.9 KB
cell narrating seven chronological status changes. This review asks why the
document ended up that way and what stops it recurring.

## Evidence

| Document | Size | Shape on inspection |
|---|---|---|
| `docs/security/risk-register.md` | 48 rows, 50.8 KB | **Accreted.** 55 inline status narrations across rows; median row 1,166 chars, worst (RISK-020) 5,093 chars with 7 stacked status entries (M1 ×2, going-public, roadmap-reshape, M8 mitigate, residual close). 36 commits touched the file; the answer to "current status?" requires reading each cell to its end. Preamble still described the pre-M1 draft-requirement world. |
| `docs/security/soup-register.md` | 30 entries, 11.6 KB | **Clean.** Uniform status vocabulary; one row per dependency; current-state only. |
| `docs/traceability/requirements-registry.md` | ~350 rows | **Clean.** Single status column with fixed vocabulary; rows replaced on state change. |
| `docs/security/threat-model.md` | 114 KB | Narrative analysis document (different genre — not a status register); no inline status accretion found. Size warrants an eventual skim-review, out of scope here. |

## Root causes

1. **The gate checks presence, not form.** FRG-PROC-006 requires security docs
   to be updated *in the same change*, and merge-gate item 5 verifies that an
   update happened. No rule ever said what an update should look like, so the
   cheapest legible evidence — an appended, date-stamped narration — became the
   norm. Every append made the next append look more correct.
2. **Deletion had no mandate.** For a security document, removing a
   predecessor's words reads as information loss unless a rule explicitly
   blesses it. Nothing did. Authors (human and agent alike) rationally chose
   the loss-averse option; the register turned into a log.
3. **Tool asymmetry predicts the outcome.** The two clean documents are the
   two with mechanical validators at the merge gate (`tools/soup_check.py`,
   `tools/trace.py`). The risk register has no validator, so its drift had no
   tripwire. The correlation is exact across the three status documents.
4. **Genre confusion.** A risk register is a *status* document: its one job is
   answering "what protects us now, and is it resolved?" at a glance. History
   is version control's job — the register lives in git, where every state
   change already lands as a commit with a `Refs:` trailer. Narrating history
   inline duplicates git, badly, at the direct expense of the document's
   actual purpose. This distinction was never written down.
5. **No consumer-eye review.** Milestone gates exercise code, tests, spec
   sync, and manual sync — never a cold read of a living document by its
   intended consumer. The first genuine consumer read (owner, 2026-07-13)
   produced this finding immediately.

## Corrective actions (this change)

- **Register compacted**: every row reduced to current state — a Status cell
  (status word + provenance: change id, version) and a present-tense Current
  mitigation cell citing governing requirement ids; review triggers kept for
  accepted risks. Preamble rewritten to describe the current register and to
  state the history convention explicitly (`git log --follow` reconstructs any
  risk's journey).
- **Commit-standard amendment** (merge-gate item 5): status-bearing living
  documents are updated by *replacing* current-state content, never by
  appending narrations; history is git's job.

## Recommendations (not implemented here — owner's call)

1. A ~30-line `tools/risk_register_check.py` at the merge gate mirroring
   `soup_check.py`: fixed status vocabulary, per-cell length ceiling,
   one-Status-marker-per-row. Root cause 3 says a validator is what actually
   keeps a register clean; the two clean documents prove it.
2. A once-per-milestone "consumer read": one living document read cold at each
   milestone close, findings filed like any other gate finding.
3. An eventual threat-model skim for the same disease in narrative form
   (out of scope today; no accretion markers found, but 114 KB deserves eyes).
