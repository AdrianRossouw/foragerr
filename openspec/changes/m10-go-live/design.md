# m10-go-live — design notes (pre-design, 2026-07-15)

Design authority for the M10 decomposition in `proposal.md`. Implementing
changes elaborate these into delta specs and scenarios; where this document
and an approved implementing change disagree, the implementing change wins.

## 1. Transport posture

**TLS is the deployment layer's job; foragerr never terminates it.** This has
been the threat model's position since RISK-004 ("TLS via DEP
Tailscale-scoped exposure"); M10 finishes it rather than inventing it. The
supported stories are Tailscale (WireGuard on every hop; `tailscale serve`
for real certificates) and a reverse proxy per linuxserver.io convention.
In-app TLS (cert loading, renewal, cipher config) is rejected: new surface
and SOUP for a feature the supported deployment does not need.

**The gap to fix**: session cookies set `secure=request.url.scheme == "https"`
(`backend/src/foragerr/auth/routes.py`). Behind any TLS-terminating proxy the
app sees plain HTTP, so `Secure` is silently never set even though the browser
is on HTTPS. Fix = an **opt-in trusted-proxy setting**: proxy headers
(`X-Forwarded-Proto`/`For`) are honored only from an explicitly configured
proxy address; default behavior (direct peer only) is unchanged. This is a
deliberate revision of the rate limiter's documented X-Forwarded-For refusal
(threat-model "DEP's TLS/proxy work" review trigger) — the same setting
governs both, so IP attribution and cookie flags stay consistent.
Misconfiguration risk (trusting a spoofable header) goes in the risk register;
the manual states plainly: set this only to the address of a proxy you run.

## 2. At-rest posture

Three storage classes, already implemented — M10 writes them down as one
position:

- **Encrypted**: UI-entered provider secrets and the Humble session cookie —
  `enc:v1:` Fernet under a scrypt-derived key from the env-only
  `FORAGERR_SECRET_KEY` (FRG-AUTH-008/011/012/013; RISK-013/041/045).
  Write-only API, log redaction self-registration.
- **Hashed, deliberately not encrypted**: admin password (scrypt), foragerr
  API keys (SHA-256), session tokens. Verify-only data; nothing to decrypt is
  stronger than encryption here — say so explicitly.
- **Plaintext by design**: library metadata (series/issues/paths) — not
  sensitive. Known exception: an operator-placed `config.yaml` key remains
  operator-file trust class (RISK-041).

**Key/data separation is the story**: a stolen DB or backup yields no
credentials without the environment passphrase. That makes the env the root
of trust, which is exactly where the **FDE recommendation** slots in — host
encryption protects what the app structurally cannot (the env, the running
host). **Full-database encryption is rejected with rationale**: against the
stolen-file threat the keystore already covers the sensitive subset; against
live-host compromise SQLCipher's key sits in the same env on the same host
and adds nothing but SOUP. Known residual restated in scope: weak operator
passphrase lowers offline brute-force cost (RISK-041 residual; manual
recommends a generated value).

## 3. V&V strategy

Mostly descriptive: the project already runs verification most shops would
envy — requirement ids, tagged tests (FRG-PROC-004), regenerable traceability
(FRG-PROC-005), tiered risk-scaled review gates. The strategy document names
this machinery as **verification**, and demonstrated fitness for intended use
as **validation** (structured dogfood → PQ, §5). It must contain, verbatim or
near: an **intended-use statement** (single-operator, self-hosted comic
library manager; OPDS reading over a private network); the risk-tiering rule
the gates already follow; the pentest as an independent verification
activity; the **qualified configuration** definition (§4); the
**operator/vendor split** ("executed qualification records are operator
artifacts, retained outside this repository; the production environment is
out of scope for the project, in every artifact, by design"); and the
third-party verification table (§7).

## 4. IQ/OQ/PQ

**Qualified configuration** = the published image, by digest, run per the
compose reference. Product code (`backend/`, `frontend/`, `Dockerfile`,
migrations) is inside; `docs/` (including records) is outside — which
formally breaks the record-commit chicken-and-egg: a record-only commit
cannot invalidate the qualification it documents. Records key off **tag +
commit SHA + image digest**, not "the repo".

**IQ** (installed correctly) — executable probes against a *running
container*: image digest matches record; OCI labels
(`org.opencontainers.image.revision`/`.version`, baked at build) agree;
required env present (`FORAGERR_SECRET_KEY`, admin bootstrap); volumes owned
by remapped PUID/PGID; migration head matches release; `/health` green;
perimeter returns 401 unauthenticated. Shipped as a doctor-style command or
`tools/` script emitting a pass/fail record.

**OQ** (operates per spec in this environment) — smoke subset of the e2e
suite packaged to run against a deployment: login works, OPDS Basic works,
rate limiter fires and backs off, backup produces a file, WS handshake honors
the Origin allowlist, connectivity probes for configured integrations.
Account-backed third parties are fixture-verified in the reference
environment (§7); the record states "fixture-verified" explicitly.

**PQ** (fulfills intended use in real operation) — the e2e user journeys
(add→monitor→grab→import→read via OPDS; manual import; pull cycle;
backup/restore) restated as acceptance criteria, demonstrated as structured
dogfood on a real deployment. The 0.9.x dogfood series is the unscripted
precedent; 1.0's PQ is the same activity with criteria stated up front and a
recorded result. E2e = verification reused as OQ; PQ = the same journeys in
real operation. One journey set, three uses.

**Non-leaky records by construction**: the schema has no fields for
hostnames, IPs, host paths, or volume sources — check id, pass/fail, version,
SHA, digest, timestamp. An accidentally shared record discloses nothing.
Records live at `docs/validation/records/vX.Y.Z.json` (repo copy canonical —
the site builder reads repository state only); the GitHub Release asset is
the courtesy copy. Re-qualification triggers: version upgrade → IQ+OQ rerun;
config change → relevant OQ subset. Qualification begins at v1.0.0; 0.x
releases render as absence, no backfill.

## 5. Release pipeline

**Order is the design**: build once → qualify that exact image → push that
exact image → publish the release with the record. A rebuild after
qualification is a different digest and definitionally unqualified.

Flow (session-driven; **CI never commits**):

1. Session merges release branch to main, tags, pushes main + tag (as today).
2. Tag-triggered workflow: secret-scan via `tools/build-image.sh` (FRG-DEP-001
   gate applies in CI), build, stand up ephemeral reference deployment
   (compose; throwaway secrets; seeded data; real SABnzbd container per §7),
   run IQ/OQ, emit record as workflow artifact, push image to GHCR on pass.
3. `/release` flow watches the run (`gh run watch`), downloads the record,
   commits it on a short-lived branch merged `--no-ff` (rule 7 intact),
   pushes. Site rebuilds; qualification chip appears.
4. `gh release create` with the record attached.

Rationale for no bot commits: local hooks (commit-msg, no-commits-on-main)
would be bypassed; a second pusher forces perpetual defensive pulls; every
commit in history should originate from a session following the process.
Give-up: push-tag-and-walk-away automation — which the project doesn't have
today and whose absence (a human-directed step in the loop) is part of the
story. Revisit-point documented: unattended releases post-1.0 would need
branch protection + CI-side trailer validation, a deliberate future decision.

Also in this change: SBOM generated from the SOUP register at release; pinned
action SHAs; dev/rc/release SemVer + release gate as coverage backstop
(activating [[release-process-idea]]); FRG-PROC-013 amendment.

## 6. Credentials

- **CI**: ephemeral `GITHUB_TOKEN` with explicit least-privilege
  `permissions:` (`packages: write`, `contents: read`), test-asserted like
  `pages.yml`'s block. No PAT involvement in publishing. GHCR package links
  to the repo automatically (provenance).
- **Session PAT**: fine-grained, single-repo, expiring. Needs contents:R/W
  (push/tags/releases) + actions:read (`gh run watch`); workflows:write only
  while workflow files are being authored, then dropped. No packages, no
  admin scope.
- **Feedback tooling**: `tools/token_check.py` probes what the ambient
  credential can do — asserts needed operations, warns on excess (classic
  `repo`-scope detection via `X-OAuth-Scopes`; fine-grained excess by probe).
  Runs at release time.
- **Credential inventory** in the threat model: three credentials total
  (session PAT, CI `GITHUB_TOKEN`, GHCR pull = none/public), each with scope,
  lifetime, revocation. Honest residual for the register: a scoped token in
  the sandbox still lets sandbox code push to this repo — accepted; blast
  radius shrunk, compensating controls are branch discipline + hooks + public
  visibility of a rogue push.

## 7. Third-party integration verification

Principle: **fixture confidence scales inversely with drift risk**; reference
OQ extends per hop as far as instantiable without anyone's account.

| Integration | Drift risk | Reference OQ (CI) | Live verification |
|---|---|---|---|
| NNTP (usenet servers) | frozen (decades) | not instantiated (OQ v1) | operator OQ |
| Newznab indexers | de facto frozen | fixtures | operator OQ probe |
| SABnzbd | stable API, self-hostable | **real container**, paused-queue contract (add, nzo_id, queue/history poll, category, failed-classification) — no usenet backend | operator OQ, full chain |
| ComicVine | documented, occasional | fixtures (mirroring real omissions, per the person_credits lesson) | operator OQ probe |
| Humble Bundle | undocumented, highest | fixtures | operator OQ; drift detected continuously by source state (`expired`, FRG-SRC-005) + health |

No personal credential (Humble cookie, indexer keys, usenet accounts) ever
enters CI: expiring personal credentials must not redden release gates, and a
"live at release time" claim about a third-party API goes stale the moment
the API drifts — the running deployment's own state machine is the durable
drift detector. Mock-NNTP full-chain reference OQ is a noted enhancement
(entire pipeline ephemeral, zero accounts), not 1.0 scope.

## 8. Site rendering of qualification

New requirement (FRG-SITE-007 candidate, allocated at the implementing
change) **beside** FRG-SITE-003, not modifying it (M6 lesson: MODIFIED deltas
restate complete scenario sets; layering avoids the hazard). `site/build.py`
scans `docs/validation/records/`, matches records to CHANGELOG releases,
renders a per-release chip ("Qualified: IQ ✓ OQ ✓" linking to the record).
Build-failing cross-checks, all derivable at build time:

- record version has no matching tag → fail
- record SHA ≠ `git rev-parse vX.Y.Z^{commit}` → fail
- committed record not an overall pass → fail (a failing record in-tree is a
  process violation; fail loudly)
- schema-invalid record → fail

Absence renders as absence: pre-1.0 entries carry no chip; one note citing
the V&V strategy explains the effective version. Trust Center gains evidence
cards (V&V strategy; qualification records with derived count) — the spec's
"acceptance reports" absence example flips to evidence exactly as the
conditional phrasing was designed to allow. Pentest is two-stage: scope
statement merges → absence entry upgrades to "planned, scope committed";
summary lands → evidence card. Authored copy may claim "protocol exists and
passes in the reference environment", never "the production deployment is
qualified". Timing: tag push renders the timeline entry; the chip appears
with the record commit minutes later — acceptable, honest, and automated as
part of `/release` so it is never forgotten.

## 9. Hardening sweep (decide-and-document; riding changes 2 and 5)

- **Security headers** (real gap, verified absent): CSP,
  X-Content-Type-Options, frame-ancestors/X-Frame-Options, Referrer-Policy.
  No CORS middleware is correct (same-origin default) — state it.
- **`/health` disclosure**: the one auth-exempt route; confirm bare 200, no
  version/migration detail to unauthenticated callers.
- **DoS envelope**: request body caps, WS connection caps, stated position on
  the zipfile-OOM residual (RISK-005).
- **Downgrade**: rollback below v0.9.0 reopens the throttling gap (RISK-020
  trigger); at minimum a manual warning, possibly a startup version-regression
  refusal.
- **Error hygiene**: generic 500s, no tracebacks in responses, no leakable
  debug flag — cheap to prove with a test.
- **Dependency cadence**: pip-audit/npm-audit at the merge gate; post-1.0
  patching SLA stated in the V&V strategy.
- **Aged residuals**: FRG-DEP-012 (diagnostic bundle) and RISK-008 (DDL
  extractor) — implement or formally re-accept with review triggers; a
  three-milestone-old backlog row reads worse than an explicit acceptance.
- **Audit durability** (change 4): owner-approved post-M8 follow-up; design
  question is attacker-erasure resistance.

## 10. Pentest

Scope committed **before** work starts: web app + API + OPDS + config review
of the compose reference; target = seeded throwaway instance with generated
data and disposable credentials; the owner's production environment is out of
scope in every artifact. PQ and the pentest share the seeded environment.
Remediation window sits between report and 1.0. Committed afterward: a
findings-and-remediations summary (consistent with the risk register's
publish-residuals posture); the raw vendor report is an operator artifact.
The posture document (§1, §2, container flags) is written to be citable by
the scope statement, so delegated controls land as reasoned positions, not
findings.
