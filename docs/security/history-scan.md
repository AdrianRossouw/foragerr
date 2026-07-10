# Repository history hygiene evidence (FRG-PROC-015)

The repository may only be made — and remain — public while a full-git-history
secret scan reports no unresolved findings. This file is the evidence record;
it is updated on every re-scan (and a re-scan is required before any
history-affecting operation is pushed to the public remote).

## Scan record

- **Tool**: gitleaks v8.24.3 (`gitleaks git`, default ruleset, full history of
  all local refs)
- **Date**: 2026-07-09
- **Scanned HEAD**: `36d7273dc3ead13ee4b624fbdf4faf15a3b08163`
  (branch `change/going-public`; 392 commits, ~7.48 MB scanned — see re-scan log)
- **Raw result**: 11 findings, all rule `generic-api-key`
- **Unresolved findings**: **0** (the 11 raw findings are dispositioned below;
  the separately-identified real credential is resolved-by-acceptance as KA-001)

## Disposition of the 11 raw findings

All 11 gitleaks findings occur in `backend/tests/**` and are synthetic,
checked-in test fixtures or regex false positives. Separately, one **real**
credential is present in git history — the owner's ComicVine API key embedded in
`docs/research/Foragerr.dc.html` — which gitleaks structurally misses (a bare
`KEY = '<40 hex>'` assignment is indistinguishable from a commit SHA to generic
rules). That finding is evaluated and **accepted** as **KA-001** in the
known-anomalies register (`known-anomalies.md`); the `.gitleaks.toml`
`bare-key-hex` rule added in that change closes the detection gap so a re-scan
now surfaces it:

| Matched value | Where | Disposition |
|---|---|---|
| `CV-SECRET-KEY-abc123` | `tests/flows_support.py`, `tests/metadata/cv_support.py`, `tests/test_comicvine_credential_resource.py` (and their historical revisions) | Deliberately fake fixture key (3 findings) |
| `sab-secret-key-4321` | `tests/downloads/test_downloadclient_crud_api.py` | Deliberately fake fixture key (1 finding) |
| `comicvine_min_interval_seconds=0.25` call-sites | `tests/test_comicvine_credential_resource.py`, `tests/metadata/test_client.py`, `tests/metadata/test_live.py` (historical revisions) | Regex false positive on a rate-limit kwarg adjacent to `comicvine_api_key=` — not a secret (7 findings) |
| Bare `KEY = '<40 lowercase hex>'` (ComicVine API key) | `docs/research/Foragerr.dc.html` (blob `495f29e`, reachable from all tags `v0.1.0`–`v0.3.5`) | **Real** credential; missed by the default gitleaks ruleset (SHA-shaped). **Accepted** per **KA-001** — resolved-by-acceptance; detection gap closed by `.gitleaks.toml` `bare-key-hex` (see `known-anomalies.md`) |

Corroborating checks (same date): no `.env` file was ever committed on any ref
(`git log --all --diff-filter=A -- '*.env' '.env*'` is empty), and the release
notes / CHANGELOG for v0.1.0–v0.3.3 were reviewed and contain no
credential-bearing or otherwise unsuitable content.

## Re-scan log

| Date | HEAD | Tool | Unresolved | Note |
|------|------|------|-----------|------|
| 2026-07-09 | `8a676db76cb337ce499b1e41f4ba5c93778351f8` | gitleaks 8.24.3 | 0 | Initial pre-flip scan (going-public change) |
| 2026-07-09 | `36d7273dc3ead13ee4b624fbdf4faf15a3b08163` | gitleaks 8.24.3 | 0 | Gate re-scan, final pre-merge HEAD (392 commits); finding fingerprint set identical to the initial scan's 11 dispositioned fixtures |
| 2026-07-10 | `e7c35bd2552c22a7aef3348f1a727b713c56deaa` | gitleaks 8.24.3 | 0 | ddl-optin-seeding gate re-scan; same 11 dispositioned fixtures. NOTE: a known credential exposure predating these scans is pending KA-001 (known-anomalies change) — gitleaks structurally misses it (bare KEY + hex); see that change for the disposition and detection-gap closure |
| 2026-07-10 | `d0a01f3c12c7b845c906618c8d3b2b819faa6450` | gitleaks 8.24.3 + .gitleaks.toml | 0 | known-anomalies gate re-scan with the repo config: 12 raw findings = 11 dispositioned test fixtures + the KA-001 blob (accepted, see KA-001) — bare-key-hex gap closure demonstrated in-scan |
| 2026-07-10 | `8bb0f40c4466a0032df6fecd299e2369effc7e24` | gitleaks 8.24.3 + .gitleaks.toml | 0 | roadmap-reshape gate re-scan: 12 findings = 11 dispositioned fixtures + KA-001 (accepted) — no new findings |
| 2026-07-10 | `fffa6b388ddbb657d51f869a4517cb09a70e4414` | gitleaks 8.24.3 + .gitleaks.toml | 0 | m4-design-shell gate re-scan: 12 findings = 11 dispositioned fixtures + KA-001 (accepted) — no new findings |
| 2026-07-10 | `a98c1739aecdb8a00a007ccca42e26e0b5f4b895` | gitleaks 8.24.3 + .gitleaks.toml | 0 | m4-shell-hotfix gate re-scan: 12 findings = 11 fixtures + KA-001 (accepted) |
| 2026-07-10 | `a9b379d0b1ba5f613545bb4a097e8e47ac2534cf` | gitleaks 8.24.3 + .gitleaks.toml | 0 | m4-library-views gate re-scan (435 commits): 12 findings = 11 dispositioned fixtures + KA-001 (accepted) — no new findings |
| 2026-07-10 | `ad6056d4bbc7a343c34ca4a2b3c22337c1ac8411` | gitleaks 8.24.3 + .gitleaks.toml | 0 | m4-logs-viewer gate re-scan: 12 findings = 11 dispositioned fixtures + KA-001 (accepted) — no new findings |
