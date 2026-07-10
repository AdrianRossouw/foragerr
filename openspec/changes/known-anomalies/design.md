# known-anomalies — design

## Context

A real, un-revocable ComicVine API key sits in public git history
(`docs/research/Foragerr.dc.html`, blob `495f29e`, in every tag
v0.1.0–v0.3.5 (17 tags)). Owner decision 2026-07-09: accept and document; no history
rewrite (disproportionate for a free rate-limited key with a replaceable
account), no rotation (provider offers none). The project lacks a controlled
artifact for accepted shipped anomalies — the risk register covers threats
and their treatments, not "this specific defect/exposure exists in the
product/repo and we are keeping it".

## Goals / Non-Goals

**Goals**: a KA register modeled on IEC 62304 known-residual-anomalies
practice; KA-001 seeded; history-scan evidence corrected (its blanket
no-credential claim is now false); the scanner blind spot closed with a
custom gitleaks rule; RISK-042 cross-link.

**Non-goals**: see proposal (no rewrite, no rotation, no retroactive KA
migration).

## Decisions

1. **Register lives in `docs/security/`**, beside the risk register and scan
   evidence, since anomalies of interest are predominantly security-adjacent
   and the three documents cross-reference. Table-of-contents header plus one
   `## KA-NNN — title` section per entry (parseable by the same doc-test
   style as the labelling tests).
2. **KA vs. RISK division**: the risk register answers "what could happen and
   how do we treat the threat"; the KA register answers "what concrete
   anomaly ships today and why is that accepted". Where both apply (KA-001),
   the risk row (RISK-042) carries the threat treatment and points at the KA
   entry for the decision record.
3. **Gitleaks custom rule in `.gitleaks.toml`** (repo root, where the gate
   re-scan picks it up automatically): flags 32+ char hex or base64 literals
   assigned to identifiers matching `(?i)\bkey\b|apikey|api_key|token|secret`
   even when bare (`KEY = '…'`), with an allowlist for `backend/tests/**`
   synthetic fixtures and this rule's own fixture. Verified by a tagged test
   running gitleaks against a synthetic file reproducing the exact KA-001
   line shape — the test skips (with a notice) when the gitleaks binary is
   absent, so the suite stays hermetic; the authoritative enforcement point
   remains the merge-gate re-scan (checklist item 7).
4. **History-scan evidence keeps its zero-unresolved invariant** by scoping
   it honestly: the FRG-PROC-015 test asserts "0 unresolved" — KA-001 is a
   *resolved-by-acceptance* finding, recorded in the disposition table with
   its KA reference. The blanket sentence "no real credential has ever been
   committed" is replaced by the accurate statement.

## Risks / Trade-offs

- [Accepted exposure is abused] → review triggers on RISK-042/KA-001
  (rate-limit exhaustion, provider abuse notice/ban, rotation support
  appearing); owner can create a replacement account.
- [Custom rule false-positives on hex-like constants] → allowlist paths +
  the digit/length thresholds; the gate re-scan surfaces FPs for disposition
  rather than blocking silently.
- [Register rots into a dumping ground] → every entry requires an owner
  decision + review trigger; the tagged test enforces required fields.

## Migration Plan

Docs + config only; no deployment impact. Rollback = revert.

## Open Questions

- None.
