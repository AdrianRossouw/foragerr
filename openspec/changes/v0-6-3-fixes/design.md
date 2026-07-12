# v0-6-3-fixes — design

## Context

`backend/src/foragerr/indexers/xml.py` is the project's ONE sanctioned XML
parser-construction site (a static guard test enforces this), configured
`forbid_dtd=True, forbid_entities=True, forbid_external=True`. The SABnzbd grab
path (`_validate_nzb`, `downloads/clients/sabnzbd.py:417`) reuses it on fetched
NZB bytes. The NZB 1.1 spec mandates a DOCTYPE header, so every real NZB is
rejected (`DTDForbidden`) before it reaches SABnzbd — confirmed live 2026-07-12
against DogNZB (fetched NZB carries
`<!DOCTYPE nzb PUBLIC "-//newzBin//DTD NZB 1.1//EN" "http://www.newzbin.com/DTD/nzb/nzb-1.1.dtd">`).
The hermetic e2e NZB fixtures omit the DOCTYPE, which is why 1963 green backend
tests never noticed.

Ride-alongs: `tools/trace.py` joins each requirement's test-file list in
discovery order (line ~138), so `matrix.md` cells reshuffle between
regenerations; and the README `sources` screenshot deliberately captured only
the unconfigured connect card — the owner has now asked for a real
connected-account capture using his own Humble session.

## Goals / Non-Goals

**Goals:**
- Spec-conformant NZBs validate and reach SABnzbd; hostile NZBs still die with
  a typed reason. Zero change to any other XML surface.
- `tools/trace.py` output is byte-stable for a given repo state.
- `docs/readme-assets/sources.png` shows the real review queue; the capture
  script can reproduce it against any connected instance.

**Non-Goals:**
- No general "configurable hardening" surface — exactly one new entry point for
  exactly one format.
- No implementation of the `E2E_LIVE_SAB` e2e tier body (stays a gated stub;
  the fix is UAT-verified against the live rig).
- No README prose changes.

## Decisions

1. **A second entry point in the same module, not a flag on the first.**
   `parse_nzb_xml(data, *, max_bytes)` lives beside `parse_untrusted_xml` in
   `indexers/xml.py` and calls defusedxml with
   `forbid_dtd=False, forbid_entities=True, forbid_external=True`. *Why*: the
   module stays the single parser-construction site (static guard unchanged);
   a boolean parameter on `parse_untrusted_xml` would invite every future
   caller to weaken itself, whereas a named NZB-specific function is
   grep-auditable and its docstring carries the justification. Security
   properties retained: entity **declarations** raise `EntitiesForbidden` even
   inside an allowed DOCTYPE (kills billion-laughs/quadratic blowup), external
   resolution stays forbidden (kills XXE), expat never fetches the DOCTYPE's
   PUBLIC/SYSTEM identifier, and the byte cap is unchanged. The DOCTYPE is
   thereby *inert*.
2. **`_validate_nzb` switches to `parse_nzb_xml`; nothing else moves.** The
   empty-check, segment-check, and typed `GrabValidationError` wrapping are
   untouched.
3. **Fixture realism.** The accepted-NZB test fixture is byte-shaped like the
   live DogNZB response (XML decl + DOCTYPE + namespaced `<nzb>` + file/segment
   groups); the rejected-NZB test embeds `<!ENTITY>` declarations inside the
   DOCTYPE. This pins both halves of the carve-out and repairs the
   fixtures-mirror-reality gap that hid the bug.
4. **Matrix determinism = sort at emission.** `', '.join(sorted(...))` on the
   test-file cell (and any other unordered join found in the same pass).
   One-time reorder diff of `matrix.md` is committed with the tool change.
5. **Screenshot step branches on live state.** The capture script's `sources`
   step queries `GET /api/v1/sources`; if a source is `connected` it navigates
   to `/sources`, waits for the review-queue rows (StoreManage), and shoots —
   otherwise it keeps the existing connect-card flow. The committed PNG is
   captured from the operator's real account at his request; the session cookie
   has no rendered representation anywhere in that UI (write-only field), so
   the capture leaks nothing beyond entitlement titles he chose to publish.

## Risks / Trade-offs

- **Weakened parse on one path**: the delta is DOCTYPE *tolerance* only; the
  attack-bearing vectors (entities, external resolution, size) remain forbidden
  — RISK-024/035/037 mitigations intact. Threat model gains a note; adversarial
  gate angle exercises entity-bomb-inside-DOCTYPE against the new entry point.
- **A future caller might reach for `parse_nzb_xml` out of convenience**: the
  docstring forbids non-NZB use; the static guard still counts parser
  construction sites, and review owns the rest.
- **Screenshot reproducibility**: the connected-state shot depends on a live
  account; the script keeps working headless against unconfigured instances
  (falls back to the connect card), so `tools/refresh-readme-shots.sh` stays
  one-command for every other shot.
