# v0-6-3-fixes — tasks

## 1. NZB DTD fix (FRG-SEC-002 / FRG-DL-003)

- [x] 1.1 Add `parse_nzb_xml` to `backend/src/foragerr/indexers/xml.py`
      (`forbid_dtd=False, forbid_entities=True, forbid_external=True`, same
      byte cap + typed-error wrapping); module docstring updated with the
      carve-out justification and the "NZB only" constraint.
- [x] 1.2 Switch `_validate_nzb` (`downloads/clients/sabnzbd.py`) to
      `parse_nzb_xml`; docstring updated.
- [x] 1.3 Tests: real-shape DOCTYPE-bearing NZB fixture accepted
      (`@pytest.mark.req("FRG-DL-003")`); entity-bomb-inside-DOCTYPE NZB
      rejected as typed failure, never POSTed
      (`@pytest.mark.req("FRG-SEC-002")`); confirm the static
      one-parser-site guard still passes.
- [x] 1.4 Baseline specs amended (sec + dl per delta files); threat model note
      (`docs/security/threat-model.md`) — RISK-024/035/037 unaffected.
- [x] 1.5 Live UAT against the standing rig: re-grab Saga #1 release through
      the API on :8793 and watch it reach SABnzbd (the M1-era bug's exact
      repro), record result in the gate evidence.

## 2. Matrix determinism (FRG-PROC-005)

- [x] 2.1 Sort unordered joins in `tools/trace.py` cell emission; regenerate
      `docs/traceability/matrix.md` once (one-time reorder diff).
- [x] 2.2 Test: matrix regeneration is byte-stable across two runs
      (`@pytest.mark.req("FRG-PROC-005")`).

## 3. README sources screenshot (owner request)

- [x] 3.1 `e2e/scripts/capture-readme-shots.ts` `sources` step: branch on
      `GET /api/v1/sources` — connected → shoot the review queue (StoreManage
      rows), else existing connect-card flow; comment updated (owner decision
      supersedes the unconfigured-only note).
- [x] 3.2 Capture against the live-connected :8793 instance; commit refreshed
      `docs/readme-assets/sources.png`.

## 4. Release (FRG-PROC-013 + merge gate)

- [x] 4.1 CHANGELOG v0.6.3 entry + `backend/pyproject.toml` → 0.6.3.
- [ ] 4.2 Small review fleet + Codex, including a dedicated adversarial angle
      on the parser carve-out (tiered policy: security-touching keeps the
      adversarial angle even at small size).
- [ ] 4.3 Full suites + e2e green; `tools/trace.py` + `tools/soup_check.py`
      exit 0; merge `--no-ff`; tag v0.6.3; gh release; archive change; delete
      branch.
