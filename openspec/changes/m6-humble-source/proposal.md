# m6-humble-source — Humble Bundle store source

## Why

The operator buys DRM-free comics on Humble Bundle and today moves them into the
library by hand. This change makes purchased comics show up in foragerr on their own:
connect the store once, and new entitlements are discovered, reviewed, matched against
the library, downloaded, and imported. It is the cleanest acquisition source foragerr
has — content the operator paid for, "manage a library you own" literally — and the
owner's most-wanted feature (2026-07-10). It is carved out of the M4–M7 standing
grant: this proposal requires explicit owner approval before implementation
(FRG-PROC-009 + carve-out).

Design authority: the v2 design handoff (docs/research, "adds Sources / store
integrations") — Sources nav item, store rail, connect card, manage/review list,
expiry banner. Auth model, sync semantics, and the companion-extension direction were
decided with the owner on 2026-07-11.

## What Changes

- **New top-level Sources area** (nav item, hub screen with store tabs, per the v2
  handoff): a generic store-source model — connection lifecycle, entitlement
  inventory, review workflow — implemented for one store, Humble Bundle. (2000 AD
  appears as a not-yet-connected placeholder tab only; no second integration.)
- **Cookie-paste authentication**: the operator logs into Humble in their own
  browser and pastes the `_simpleauth_sess` session cookie into the connect card.
  Stored server-side, encrypted via the m6-keystore (FRG-AUTH-008 et al. — hard
  dependency, lands first). Connect validates the cookie live before saving. No
  password is ever stored; no login automation.
- **Entitlement sync**: scheduled poll (default daily) + manual "Sync now" diffs the
  Humble order API against known entitlements; comic items are filtered in (non-comic
  bundle contents remain visible under a toggle, never silently dropped).
- **Review-first workflow**: new entitlements land as *New* with a proposed library
  match; the operator matches / adds / ignores (bulk-capable). **Nothing downloads
  without operator action by default** — an *Auto-sync new purchases* toggle exists
  and **ships OFF** (owner decision 2026-07-11, GetComics-incident lesson).
  **Divergence flag**: the design mock shows this toggle ON by default; spec follows
  the owner decision (OFF) — noted for explicit approval here.
- **Collected-edition reconciliation**: Humble sells mostly trades/collections; a
  matched edition shows exactly which tracked single issues it fills and never
  suppresses or double-counts an owned single (extends the FRG-SER-019 invariant to
  source reconciliation; edge behaviors per the handoff's sources-edge screen).
- **Download + import**: accepted entitlements fetch the signed, time-limited URL,
  verify md5, and hand off to the existing import pipeline as normal imports.
- **Session expiry is a first-class state**: 401/expiry pauses sync (no retry storm),
  flips source status, raises the global banner + amber health per the handoff;
  re-pasting the cookie resumes. Synced/imported content is never removed on expiry
  or disconnect.
- **Security docs in the same change** (FRG-PROC-006): new outbound integration and
  a parser of store-controlled JSON → STRIDE rows, risk-register entries (cookie at
  rest [mitigated by keystore], SSRF/egress on signed URLs, store-JSON parsing),
  threat-model update.
- **New AREA `SRC`** added to the commit-standard AREA table; requirement IDs
  FRG-SRC-001..007 + FRG-UI-027 allocated in the registry.

## Capabilities

### New Capabilities

- `sources`: store-source integrations — source connection lifecycle, entitlement
  sync and review, collected-edition reconciliation, entitlement download
  (FRG-SRC-001..007).

### Modified Capabilities

- `ui`: new requirement FRG-UI-027 — Sources screen (rail, connect card, manage/review
  list, expiry banner + health wiring) per the v2 handoff. (Additive; no existing UI
  requirement's behavior changes.)

## Impact

- **Code**: new `backend/src/foragerr/sources/` (models, Humble client, sync command,
  reconciliation, API routes); frontend Sources screen + nav + global banner + health
  wiring; alembic migration (sources + entitlements tables); scheduler entry for the
  sync command; import-pipeline handoff.
- **Dependencies**: none expected beyond existing httpx/pydantic; keystore change
  (m6-keystore) is a merge-order dependency.
- **Security**: new attack surface as listed above; the Humble cookie is the most
  sensitive secret foragerr will hold — it is keystore-encrypted, redaction-
  registered, write-only in API responses (existing SecretStr pattern).
- **Manual**: new `docs/manual/user/sources.md`; admin secrets/configuration notes
  (cookie handling, expiry cadence); README screenshot set gains the Sources screen.
- **Verification constraint**: the Humble order-API shape (endpoints, JSON fields,
  signed-URL format) is documented from prior art and MUST be verified against live
  operator-captured responses before implementation of the client begins (task 1.1;
  the sandbox cannot reach Humble).

## Non-goals

- **The companion browser extension** — separate follow-up change (copy-only
  forever, decided 2026-07-11); the connect card's helper text references it as
  "coming soon" per the handoff.
- **Stored email/password or automated login** — explicitly rejected auth model.
- **Any second store integration** (2000 AD, archive.org) — the model is generic,
  but only Humble is implemented; the next source proves the abstraction.
- **DRM-bearing or non-owned content acquisition** — this source only surfaces what
  the operator's account owns.
- **Torrent/usenet interaction** — entitlement downloads bypass indexers/download
  clients entirely (direct signed-URL fetch).
- **Format preferences / CBR→CBZ shifting** (parked 2026-07-11).

## Approval

**Approved by Adrian, 2026-07-11** (planning session; satisfies FRG-PROC-009 and the
standing-grant carve-out for the Humble importer). Divergence resolved by owner:
**auto-sync ships OFF as spec'd** — the design mock's ON default does not apply.
Implementation may begin at M6 after m6-keystore merges; the Humble client work
remains gated on the task 1.1 live API capture.
