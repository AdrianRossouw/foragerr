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
    blob remains, accepted here).
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
- **Status**: Accepted.
