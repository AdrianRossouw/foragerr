# foragerr — Known-Anomalies Register (FRG-PROC-016)

This register records every anomaly the owner decides to **accept rather than
fix** — a shipped defect, a process deviation, or an exposure persisting in
published artifacts. It is the controlled place for "this concrete
defect/exposure exists in the product or repository and we are keeping it",
distinct from the risk register (which records threats and their treatments).
The practice follows IEC 62304 §5.8's handling of known residual anomalies.

Rules:

- Each anomaly gets a stable `KA-NNN` identifier. **IDs are never reused or
  renumbered.**
- **Entries are never deleted.** An anomaly later eliminated by a change is
  marked resolved with a reference to the fixing change; the entry and its ID
  remain permanently.
- Every entry carries: **Description**, **Location/scope**, **Discovered**,
  **Impact evaluation**, **Owner decision** (date + rationale), **Mitigations**,
  **Review trigger**, and **Status**.
- A change whose release accepts a new anomaly references the KA identifier in
  its release notes (FRG-PROC-016).
- Structural consistency is enforced by tagged tests
  (`backend/tests/test_known_anomalies.py`, FRG-PROC-016).

---

## KA-001 — Un-revocable ComicVine API key in public git history

- **Description**: The owner's real, production ComicVine API key — a
  40-character lowercase-hex ComicVine API key — is embedded in a
  design-prototype export as a bare JavaScript class-field assignment of the
  shape `KEY = '<40 lowercase hex chars>';`. Because it is a bare `KEY`
  identifier assigned a pure-hex literal, the value is indistinguishable from a
  commit SHA to generic secret-scanning rules, which is why three scanners
  (gitleaks 8.24.3, the repository keyword sweep, and `tools/build-image.sh`)
  all missed it (they key on `api_key`/`secret`/`password`/`token`-style
  compound identifiers). The key cannot be revoked: ComicVine offers no key
  rotation and no account deletion. It sits in git history reachable from every
  release tag; a history rewrite has been explicitly rejected (see Owner
  decision), so the value remains public.
- **Location/scope**: `docs/research/Foragerr.dc.html` (a design-exploration
  export). Introduced by commit `495f29e` (2026-07-05, "docs(research): add
  Adrian's Foragerr design-exploration file"). That blob is reachable from
  every release tag `v0.1.0` through `v0.3.5` and from all branches. The
  working-tree copy is removed in this same change; the historical blob remains.
- **Discovered**: 2026-07-09, prompted by a design-handoff README that
  described the key as a "throwaway" (it is not — it is the production key). The
  repository had become public earlier that day. At discovery GitHub reported
  **0 clones, 0 forks, 0 stars**.
- **Impact evaluation**: The key is a free, rate-limited ComicVine metadata
  key. It carries **no billing, no PII, and no account-takeover surface** —
  ComicVine accounts are read-only metadata consumers. Worst case: a third
  party who extracts the key from history uses it and either exhausts its
  rate limit or triggers a provider-side abuse ban. Recovery from either is to
  create a new ComicVine account for a fresh key. An abuser gains nothing they
  could not obtain by registering their own free ComicVine account in seconds,
  which lowers the practical incentive to harvest this one.
- **Owner decision** (2026-07-09, Adrian): **Accept and document.** A history
  rewrite is explicitly **rejected** as disproportionate: the repository had
  only just been published, all 17 release tags (`v0.1.0`–`v0.3.5`) reference
  the blob so every tag would have to be rewritten, the key is low-value (free,
  rate-limited, no billing/PII/account access), zero clones were observed at
  discovery, and an abuser would sooner register their own free key than harvest
  this one. Key rotation is not possible (provider offers none) and is not
  attempted. The owner can create a replacement ComicVine account for a fresh
  key if this one is ever banned.
- **Mitigations**:
  - A repo-root `.gitleaks.toml` custom rule (`bare-key-hex`) closes the
    detection gap that let this class of secret through, so any recurrence of a
    bare `KEY = '<hex>'`-shaped credential is flagged at the merge-gate re-scan.
  - The working-tree copy of `docs/research/Foragerr.dc.html` is removed in this
    change, so the current tree no longer republishes the key (the historical
    blob remains, accepted here). Diffs and patches of that removal necessarily
    display the historical value; this adds no exposure beyond the accepted
    public blob itself.
  - Design handoffs are kept **out of the repository** going forward (owner
    direction 2026-07-10), removing the class of file that introduced this
    exposure.
  - The key remains valid in production and is supplied via `.env`
    (environment / gitignored), which is never committed; the exposed copy is
    the design-export literal only.
- **Review trigger**: Any sign of third-party use — unexplained rate-limit
  exhaustion, a ComicVine abuse notice, or a provider-side ban — or ComicVine
  introducing key rotation. On a ban, create a replacement account. If key
  rotation becomes available, rotate the key and mark this entry **resolved**
  with a reference to the resolving change.
- **Risk register**: RISK-042 carries the corresponding threat treatment
  (`docs/security/risk-register.md`).
- **Status**: Accepted.

---

## KA-002 — Series titles ending in "Issue"/"Issues" do not survive a rename round-trip

- **Description**: The FRG-IMP-026 issue-word filler strip removes a bare
  `Issue`/`Issues` token immediately preceding a file's issue evidence. A
  series whose title *ends* in that word (e.g. a hypothetical "The Death
  Issue") produces renamed files of the shape `The Death Issue 004 (2019).cbz`
  (default template, and equally with a `#` anchor), which re-parse with the
  final title word stripped — `matching_key` drifts from `death issue` to
  `death`, so a rescan of the renamed file no longer subset-matches its own
  series. The ambiguity is structural: `<Title ending in "Issue"> <number>`
  and `<Title> Issue <number>` are identical token streams, so no parser-side
  rule can distinguish them. A same-rooted, one-time consequence: persisted
  Library Import staging groups keyed by a pre-upgrade `matching_key`
  containing the filler word (e.g. `foo issues`) lose their carried
  confirm/skip decision on the first re-scan after upgrading, because the key
  the new parser computes no longer matches the stored one.
- **Location/scope**: `backend/src/foragerr/parser/__init__.py`
  (`_consume_issue_filler`); carry-forward keying in
  `backend/src/foragerr/library/flows/library_import.py` (`scan_library_root`).
- **Discovered**: 2026-07-28, during the m11-source-import-trust merge gate
  (implementer-flagged in commit 91330b4; blast radius verified by the
  API/regression review angle, including the `#`-anchor non-mitigation).
- **Impact evaluation**: Low. No known real ComicVine series title ends in a
  bare "Issue"/"Issues"; the strip fires only with the filler directly before
  the issue evidence, and mid-title uses are unaffected (corpus row 87). The
  library-import consequence costs at most a re-answered review decision for
  staged-but-unexecuted groups whose folder names carry the idiom across this
  one upgrade — no comic files or library records are touched. The
  countervailing benefit is large: the idiom is pervasive in real store
  filenames (verified on the live 1,318-item collection) and previously
  defeated import matching outright.
- **Owner decision**: Accepted under the M11 standing grant (2026-07-27);
  queued for explicit owner review at the M11-close hard stop. Fixing would
  require either forking the cue vocabulary (rejected: FRG-IMP-016 keeps one
  vocabulary) or suppressing the strip when a library series' own key retains
  the filler word — a context-dependent parse the parser's pure-function
  contract forbids (parse results must not depend on library state).
- **Mitigations**:
  - Corpus rows 82–87 pin both the strip and the mid-title preservation, so
    the boundary cannot drift silently.
  - The importer's series-scoped paths (provenance, rescan) match issues
    within a known series and do not depend on the parsed title, which
    removes the main consumer of the drifted key for affected files.
  - Release notes for the shipping version reference this entry
    (FRG-PROC-016), covering the one-time library-import staging note.
- **Review trigger**: A real series title ending in bare "Issue"/"Issues"
  appearing in ComicVine data used by an operator, or any rescan mis-match
  traced to the stripped key. If encountered, revisit the
  series-key-aware suppression option as its own change and mark this entry
  resolved with a reference to it.
- **Status**: Accepted.
