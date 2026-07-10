# known-anomalies — a known-anomalies register, seeded with the exposed ComicVine key

## Why

On 2026-07-09 a real, un-revocable ComicVine API key was found embedded in
`docs/research/Foragerr.dc.html` — committed 2026-07-05 (`495f29e`), contained
in every release tag, and public since the repository visibility flip. Three
scanners missed it (gitleaks 8.24.3, the repo keyword sweep, and the
build-image scanner: the line is a bare `KEY = '<40 hex>'`, indistinguishable
from a commit SHA to generic rules). The owner evaluated the exposure and
decided to **accept and document** rather than rewrite history: the key is
free, rate-limited, carries no billing or account access, an abuser would
sooner register their own free key, a replacement account is possible if the
provider ever bans it, and rewriting a just-published repository's entire
tag history is disproportionate. The project currently has no controlled
place to record such a decision — accepted *risks* live in the risk register,
but an accepted *defect/exposure that ships* is a different artifact. Regulated
software practice (IEC 62304 §5.8's known residual anomalies) keeps a
known-anomalies list for exactly this, and foragerr needs one for proper
change control going forward.

## What Changes

- **New controlled document** `docs/security/known-anomalies.md`: the
  known-anomalies register. Every anomaly the owner accepts rather than fixes
  — a shipped defect, a deviation, or an exposure persisting in published
  artifacts — gets a stable `KA-NNN` entry: description, location/scope,
  impact evaluation, owner decision with date and rationale, mitigations, and
  a review trigger. Entries are never deleted; a later fix marks them
  resolved with a reference.
- **Seed entry KA-001**: the exposed ComicVine key, with the full evaluation
  and the accept decision above.
- **`docs/security/history-scan.md` corrected**: its "no real credential has
  ever been committed" claim is now false and is rewritten to reference
  KA-001; the finding and its disposition (accepted, un-revocable, documented)
  are recorded per FRG-PROC-015.
- **Scanner gap closed**: a repo-root `.gitleaks.toml` custom rule catching
  the missed class (bare `KEY`-ish identifier assigned a 32+ hex/base64
  literal outside test fixtures), so gate re-scans flag any recurrence; the
  merge-gate checklist references the config.
- **Risk register**: RISK-042 records the residual (third-party use of the
  published key), cross-linked to KA-001, with review triggers (abuse signs,
  provider ban, rotation support appearing).
- **Tagged consistency test** (FRG-PROC-016): register entries have unique
  stable IDs and all required fields; KA-001 exists; the gitleaks config
  detects the KA-001 line shape (regression-proof via a synthetic fixture).

## Non-goals

- **No history rewrite** — explicitly rejected by the owner (recorded in
  KA-001).
- **No key rotation or .env change** — the key remains valid and in
  production use; the provider offers no rotation.
- **No retroactive KA entries** beyond KA-001 — older accepted residuals
  already live in the risk register and stay there; the KA register applies
  from this change forward (risk-register acceptances that are *anomalies*
  may migrate opportunistically later).

## Capabilities

### Modified Capabilities

- `dev-process`: one new requirement —
  - **FRG-PROC-016 — Known-anomalies register**: accepted
    defects/deviations/exposures are recorded as stable, never-deleted
    `KA-NNN` entries with impact evaluation, owner decision, mitigations, and
    review trigger; the register is a controlled document checked by tagged
    tests; release notes for a change that accepts an anomaly reference its
    KA ID.

## Impact

- **Files**: `docs/security/known-anomalies.md` (new),
  `docs/security/history-scan.md` (correction + disposition),
  `docs/security/risk-register.md` (RISK-042), `.gitleaks.toml` (new),
  `docs/process/commit-standard.md` (checklist item 7 references the config),
  `backend/tests/test_public_labelling.py` or a new test module (tagged
  FRG-PROC-016), registry row FRG-PROC-016, dev-process delta spec.
- **Manual impact (FRG-PROC-011)**: none — no user/admin-facing behavior
  changes (rationale: process/security documentation only).
- **SOUP (FRG-PROC-012)**: none.
- **Security (FRG-PROC-006)**: no new attack surface; documents an existing
  exposure and closes a detection gap.

## Approval

Approved by Adrian, 2026-07-10 ("and known anomolies change is approved").
The accept-the-exposure decision itself was made 2026-07-09 ("i think we can
document it and accept... i could always create another account... somebody
could also register their own free account"). Scope additions agreed in the
same conversation: remove the working-tree copy of the key-bearing design
export (docs/research/Foragerr.dc.html) so the current tree stops
republishing it, and record the owner's FRG-AUTH-008 direction (encryption
key from environment only, never a file) as a note on RISK-041.
