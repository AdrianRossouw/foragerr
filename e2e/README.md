# foragerr end-to-end harness (FRG-PROC-010)

A browser-driven Playwright suite that drives the **real container image** — UI,
API and OPDS — the way a user would, catching integration seams the per-change
unit/contract suites structurally cannot. External services are mocked by
default (hermetic); an env-gated live tier is structured but not required.

## Run it

```bash
bash e2e/run.sh          # from the repo root — build image, up, test, report, down
```

One command: builds `foragerr:e2e`, generates fixture TLS + the canonical cbz,
brings up the compose stack, waits for `/health`, seeds a root folder, runs the
suite headless, writes `e2e/acceptance-report.md`, and tears everything down.
Exit code is Playwright's — non-zero when a scenario fails; the report names the
failure. Traces/screenshots for failures land under `e2e/results/`.

Useful env: `E2E_KEEP_UP=1` leaves the stack running for debugging;
`E2E_SKIP_BUILD=1` reuses an already-built `FORAGERR_IMAGE`.

## What it covers

The spine (`tests/spine.spec.ts`, serial — the library grows across steps):

1. **first run** — container healthy, SPA served (`FRG-DEP-007/001`).
2. **add a series** from the ComicVine fixture; refresh lands issues
   (`FRG-SER-005`, `FRG-UI-005`).
3. **interactive search** renders **verbatim** rejection reasons (`FRG-UI-007`,
   `FRG-SRCH-001`).
4. **grab → download → import → renamed file** in the library, byte-identical to
   the source (`FRG-DDL-010`, `FRG-DL-007`, `FRG-PP-009/010`).
5. **library browse** with updated stats (`FRG-UI-003`, `FRG-SER-009`).
6. **OPDS** navigation → download with the correct comic MIME
   (`application/vnd.comicbook+zip`), byte-identical to the library file
   (`FRG-OPDS-001/002/003/005`).
7. **live-SAB tier** — skipped cleanly unless `E2E_LIVE_SAB=1` and SABnzbd /
   news-server credentials are present (the hermetic tier is the deliverable).
8. **library import** (`tests/y-library-import.spec.ts`, runs after the spine)
   — a pre-existing folder tree seeded under the `/library` root is scanned
   into staged groups (AppleDouble/zero-byte junk skipped, `FRG-IMP-022`);
   review renders the proposed ComicVine match (Fables, the second mockhub
   volume) and an explicit no-match group that cannot be selected; confirming
   and importing with batch options lands the series **in place** — issues
   show `has_file` with the files renamed per the naming template inside the
   scanned folder (never moved out of it, byte-identical) and no download
   involved (`FRG-UI-015`, `FRG-IMP-023`).
9. **restart resilience** — `docker restart` mid-flight; library + persisted
   command queue survive (`FRG-SCHED-002`).
10. **unconfigured key** (`tests/zz-unconfigured.spec.ts`, runs last) — the app
   container is recreated with an explicitly **empty** ComicVine key
   (`E2E_CV_API_KEY=` against compose's `${E2E_CV_API_KEY-e2e-example-key}`);
   an Add Series search renders the actionable credential error pointing at
   Settings, never the plain "no results" state (`FRG-UI-005`).

Each test title names the FRG ids it exercises;
`scripts/acceptance-report.mjs` converts the Playwright JSON reporter output
into `acceptance-report.md` (scenario → ids → pass/fail/skipped). There is no
hand-authored criteria matrix.

## Coverage limits

The hermetic fixtures deliberately model ONE happy DDL path so the whole
download→verify→import→OPDS chain runs in-process. Read the generated
`acceptance-report.md` with these gaps in mind — a GREEN verdict does **not**
attest to any of the following, which the fixtures do NOT exercise:

- **Multi-host DDL landing-page parsing / failover.** The GetComics fixture
  serves one first-party download link. Real GetComics posts link out to
  pixeldrain / mediafire / mega / zippyshare mirrors with host-specific landing
  pages and failover between them — none of that HTML-scraping or host-selection
  logic is driven here.
- **Real redirect chains.** The fixture download endpoint returns the bytes
  directly; real DDL hosts bounce through multiple 3xx hops (and interstitials)
  before the file. The redirect-walk / hop-check code paths are only
  unit-tested, not end-to-end here.
- **Real SABnzbd / usenet.** The usenet+SAB grab→poll→import path is only
  covered by the env-gated **live tier** (`E2E_LIVE_SAB=1` + credentials); the
  default hermetic run skips it. A hermetic GREEN says nothing about SAB.
- **Real ComicVine / Newznab upstreams.** Metadata and indexer responses come
  from the in-repo mock, not the live services.

## Download path: built-in DDL, not usenet/SAB

The grab drives the **built-in DDL client** (GetComics-shaped fixture pages +
direct file download), chosen because it completes the whole
download→verify→import chain **in-process** on the same filesystem the importer
reads — no fake SABnzbd, no shared download volume, no async poll timing. The
usenet/SAB path is available as the live tier.

## Topology (`compose.yaml`)

- **foragerr** — the built image, fresh `/config` + `/library` per run.
- **mockhub** — one fixture process (built `FROM` the app image to reuse its
  venv) serving three upstreams:
  - **ComicVine** over http (`/api/*`) — the app is pointed here via
    `FORAGERR_COMICVINE_BASE_URL` (the one sanctioned e2e-only override).
  - **Newznab** over http (`/newznab/api`) — a deliberately-old release that the
    decision engine rejects for retention, giving the overlay a verbatim reason.
  - **GetComics** over https (host `getcomics.org`) — the approved release the
    DDL client grabs and downloads.

### Two constraints the harness works around (without weakening production)

1. **Egress policy (FRG-SEC-001)** refuses loopback/link-local/RFC-1918. Docker
   default bridges are RFC-1918, which the app would reject. The e2e network
   therefore uses **TEST-NET-3 `203.0.113.0/24`** — a non-RFC-1918 subnet the
   policy accepts, exactly as the unit suite's `PUBLIC_V4` does. No product
   change; a compose-only network choice.
2. **DDL is https-only** and TLS verification is always on. The harness mints a
   throwaway CA + `getcomics.org` leaf at run time (outside the repo, never
   committed) and appends the CA to the app container's certifi bundle at start
   via a compose `entrypoint` wrapper — no image or product change.

## SOUP note

`e2e/package.json` (Playwright, TypeScript) is dev/test tooling and is outside
the scope the SOUP register declares (it tracks the product manifests it names);
no register rows are added for it. See the change proposal's impact section.
