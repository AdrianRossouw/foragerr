# m6-humble-source — tasks

## 1. API schema & fixtures

- [ ] 1.1 ~~Owner live capture~~ DONE VIA PRIOR-ART DISSECTION (owner direction 2026-07-11): schema documented in `docs/research/humble-api.md` from three OSS clients (incl. one pushed 2026-06); build synthetic fixtures from it (comic bundle w/ CBZ+PDF twins, collected edition, EPUB-only book, game item, malformed subproduct)
- [ ] 1.2 Finalize comic-classification rule (platform=="ebook" + format/extension) and auto-match confidence threshold against the fixtures; record in design.md. LIVE VALIDATION MOVES TO UAT: first real connect+sync against the operator's account confirms schema + CDN egress allowlist (expected dl.humble.com); any drift updates client + fixtures together

## 2. Backend model & client

- [ ] 2.1 Alembic migration: `sources` + `source_entitlements` tables; SQLAlchemy models (`FRG-SRC-001`)
- [ ] 2.2 Humble client module: order list/detail, fixture-driven tests, politeness/backoff (NFR-005), bounded requests (NFR-006); cookie as SecretStr through the keystore path (`FRG-SRC-002`)
- [ ] 2.3 Connect/validate/disconnect service + API routes; cookie write-only in responses; disconnect deletes credential, keeps data (`FRG-SRC-001`, `FRG-SRC-002`)
- [ ] 2.4 Sync command on the scheduler (default daily) + Sync-now endpoint: store-native-key diff, comic/other classification, skip-and-log malformed entries, idempotent re-sync (`FRG-SRC-003`)
- [ ] 2.5 Expiry handling: 401 → `expired`, pause, health contribution, reconnect resumes (`FRG-SRC-005`)

## 3. Review workflow & reconciliation

- [ ] 3.1 Entitlement review actions (match/add/ignore/restore, single + bulk) with proposed-match computation via existing ranking + booktype/containment (`FRG-SRC-004`)
- [ ] 3.2 Auto-sync toggle, default OFF; confident-match auto-accept path when ON (`FRG-SRC-004`)
- [ ] 3.3 Reconciliation module: fills-range computation, owned-single preservation, OGN/artbook standalone path; three-way invariant proof tests mirroring FRG-SER-019 (`FRG-SRC-007`)

## 4. Download & import

- [ ] 4.1 Grab path: fresh signed URL at grab time, HTTPS + CDN allowlist enforcement, size/timeout bounds, md5 verify, staging handoff to import pipeline (`FRG-SRC-006`)
- [ ] 4.2 Failure paths into the existing failed-download surface with retry; checksum-mismatch quarantine test (`FRG-SRC-006`)

## 5. Frontend

- [ ] 5.1 Sources route + nav item with badge states; store rail with placeholder tab (`FRG-UI-027`)
- [ ] 5.2 Connect card (paste field, helper with extension-coming-soon chip + DevTools steps, live-validated Connect, privacy note) (`FRG-UI-027`)
- [ ] 5.3 Manage view: account bar, count line, filter segments, entitlement rows + expand detail with issue chips per edge rules; bulk + shift-range select (`FRG-UI-027`)
- [ ] 5.4 Global banner + amber header/footer health wiring over the health WS; e2e covering connect, review, expiry (negative path per UAT policy: unconfigured + expired states) (`FRG-UI-027`)

## 6. Security, docs, traceability

- [ ] 6.1 STRIDE rows: cookie credential (at rest/in transit/clipboard residual), Humble JSON parsing, signed-URL egress; risk-register entries; threat-model update (FRG-PROC-006)
- [ ] 6.2 Manual: `docs/manual/user/sources.md` (connect, review, expiry, auto-sync semantics); admin notes; README labelling + screenshot set gains Sources
- [ ] 6.3 Registry: SRC AREA row in commit-standard table; FRG-SRC-001..007 + FRG-UI-027 → implemented; matrix regen; SOUP check green (no new deps expected)
- [ ] 6.4 CHANGELOG + release notes; version bump

## 7. Gate

- [ ] 7.1 Full suite green; security-touching tier → full 8-angle fleet + adversarial angle with a tested cookie-leak scenario + Codex; merge-gate checklist
