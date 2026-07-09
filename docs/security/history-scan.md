# Repository history hygiene evidence (FRG-PROC-015)

The repository may only be made — and remain — public while a full-git-history
secret scan reports no unresolved findings. This file is the evidence record;
it is updated on every re-scan (and a re-scan is required before any
history-affecting operation is pushed to the public remote).

## Scan record

- **Tool**: gitleaks v8.24.3 (`gitleaks git`, default ruleset, full history of
  all local refs)
- **Date**: 2026-07-09
- **Scanned HEAD**: `8a676db76cb337ce499b1e41f4ba5c93778351f8`
  (branch `change/going-public`; 388 commits, ~7.45 MB scanned)
- **Raw result**: 11 findings, all rule `generic-api-key`
- **Unresolved findings**: **0**

## Disposition of the 11 raw findings

All 11 occur in `backend/tests/**` and are synthetic, checked-in test fixtures
or regex false positives — no real credential has ever been committed:

| Matched value | Where | Disposition |
|---|---|---|
| `CV-SECRET-KEY-abc123` | `tests/flows_support.py`, `tests/metadata/cv_support.py`, `tests/test_comicvine_credential_resource.py` (and their historical revisions) | Deliberately fake fixture key (3 findings) |
| `sab-secret-key-4321` | `tests/downloads/test_downloadclient_crud_api.py` | Deliberately fake fixture key (1 finding) |
| `comicvine_min_interval_seconds=0.25` call-sites | `tests/test_comicvine_credential_resource.py`, `tests/metadata/test_client.py`, `tests/metadata/test_live.py` (historical revisions) | Regex false positive on a rate-limit kwarg adjacent to `comicvine_api_key=` — not a secret (7 findings) |

Corroborating checks (same date): no `.env` file was ever committed on any ref
(`git log --all --diff-filter=A -- '*.env' '.env*'` is empty), and the release
notes / CHANGELOG for v0.1.0–v0.3.3 were reviewed and contain no
credential-bearing or otherwise unsuitable content.

## Re-scan log

| Date | HEAD | Tool | Unresolved | Note |
|------|------|------|-----------|------|
| 2026-07-09 | `8a676db76cb337ce499b1e41f4ba5c93778351f8` | gitleaks 8.24.3 | 0 | Initial pre-flip scan (going-public change) |
