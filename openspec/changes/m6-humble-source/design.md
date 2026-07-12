# m6-humble-source — design

## Context

Sources are a genuinely new concept in the *arr model: indexers and download clients
are pure configuration, but a store source has **inventory** — a browsable list of
things the account owns, each with per-item state and review actions (owner insight,
2026-07-11). The v2 design handoff supplies the complete interaction model: Sources
nav + hub with store tabs; connect card (cookie paste + helper); manage view with
account bar, count line, filter segments, and an entitlement list with per-status
actions and an expandable reconcile detail; expiry wired to a global banner, sidebar
footer, and header health. This design maps that model onto the backend.

Hard dependency: m6-keystore (FRG-AUTH-008/011/012/013) merges first; the cookie is
born encrypted.

## Goals / Non-Goals

**Goals:**
- Generic source/entitlement model, one concrete store (Humble).
- Review-first acquisition: operator action between discovery and download by default.
- Reconciliation that extends the never-suppress-singles invariant (FRG-SER-019).
- Expiry/disconnect as modeled states with zero data loss.

**Non-Goals:** browser extension (next change); second store; login automation;
generic webhook/push discovery (poll only).

## Decisions

1. **Data model: `sources` + `source_entitlements` tables.** A source row: type
   (`humble`), settings JSON (cookie as `SecretStr` → keystore-encrypted
   automatically), connection state (`connected` / `expired` / `disconnected`),
   last-sync metadata. An entitlement row: source FK, store-native key (gamekey +
   subproduct machine name — stable diff identity), display fields (title, publisher,
   format, collects-range), content classification (`comic` / `other`), review status
   (`new` / `matched` / `ignored`), match target (series/collection ref), download
   state, md5/size/filename from the API, timestamps. *Why store-native key as
   identity*: sync is a diff; the key must survive title edits and re-syncs.
2. **Status model: review status and download state are separate axes.** The
   handoff's user-facing statuses (New / Matched / Ignored) are the review axis;
   download/import progress (queued → fetching → verifying → imported → failed) is
   the existing-pipeline axis surfaced in Activity, not a new UI concept. *Why*:
   keeps the Sources list a review surface (design intent) and reuses queue
   infrastructure instead of duplicating progress UI.
3. **Humble client** (`sources/humble.py`): `GET /api/v1/user/order` → gamekeys;
   `GET /api/v1/order/{gamekey}?all_tpkds=true` → subproducts → `download_struct`
   (signed time-limited `url.web`, md5, size, filename). Cookie rides as
   `_simpleauth_sess`. **Shape confirmed by prior-art dissection** — see
   `docs/research/humble-api.md` (three OSS clients, one actively maintained as
   of 2026-06); fixtures are built from that schema, and live validation happens
   at UAT against the operator's account (sandbox cannot reach Humble). Client
   honors FRG-NFR-005 politeness/backoff and FRG-NFR-006 bounded-verified-
   outbound rules.
4. **Comic filtering**: classify subproducts by download format/extension (cbz/pdf/
   cbr) and bundle category hints — exact rule finalized against captured fixtures.
   Non-comic items are stored with classification `other` and shown under the
   design's toggle; never silently dropped (misclassification is discoverable and
   an operator can reclassify via Match/Add actions).
5. **Sync**: a scheduled command (existing sched/queue framework, crash-safe,
   idempotent per FRG-NFR-007), default daily + "Sync now". Diff by store-native
   key; new comic items → review status `new` with a **proposed match** computed
   server-side (existing ComicVine/library match ranking + booktype/containment
   from v0.4.4). A 401 mid-sync → source state `expired`, sync pauses (no retry
   storm), partial results kept.
6. **Auto-sync toggle ships OFF** (owner 2026-07-11, overriding the mock's ON
   default): when ON, `new` items with a confident match auto-advance to accepted +
   download; when OFF (default), everything waits in review. The toggle copy in the
   mock ("matched/added automatically") maps to exactly this.
7. **Reconciliation** (`sources/reconcile.py`): a matched collected edition
   computes the tracked-issue set it fills; issues already owned as singles are
   kept (never replaced, never double-counted) and chipped amber in the detail
   panel; >12-issue ranges render text-only (handoff edge rules). This is the
   FRG-SER-019 invariant extended to sources: reconciliation NEVER writes a
   wanted-suppression, it only marks issues owned-via-edition. OGN/artbook items
   with no single issues add as one-shots / stay out, per the handoff.
8. **Download path**: accepted entitlement → fetch signed URL (fresh from the order
   API at grab time — stored URLs expire) → stream to the existing download
   staging area → md5 verify → hand to the import pipeline as a normal completed
   download. Failures land in the existing failed-download surface with retry.
9. **API**: `/api/v1/sources` CRUD + `/sources/{id}/sync` + entitlement list/action
   endpoints (match/add/ignore/restore, bulk). Cookie is write-only in responses
   (existing SecretStr pattern); connect performs a live validation call before
   persisting.
10. **Frontend**: new Sources route per the handoff component tree (SourcesRail,
    ConnectCard, StoreManage with ItemList/ExpandDetail); GlobalBanner + health
    wiring reuse the existing health WS. Bulk review actions reuse the M4
    bulk-selection pattern (FRG-UI-025), including shift-range select.

## Risks / Trade-offs

- [Humble changes internal API/cookie semantics] → unofficial API; client isolated
  in one module, fixtures pinned from captured responses, failures degrade to the
  expired/attention state (never crash sync scheduler); manual paste is the
  permanent fallback auth.
- [Cookie theft = full Humble account access] → keystore encryption at rest,
  redaction, write-only API, never sent to the frontend; residual risk on the OS
  clipboard during paste (same as manual flow) — STRIDE row + risk-register entry.
- [SSRF/egress via signed URLs] → downloads restricted to https + humblebundle
  CDN host allowlist derived from captured fixtures; bounded size + timeout per
  FRG-NFR-006; STRIDE row.
- [Store-controlled JSON parsing] → pydantic-validated models, size caps, defensive
  defaults; malformed orders skip-and-log, never abort the whole sync.
- [Misclassification hides a comic] → `other` items visible under toggle;
  reclassify action.
- [Wrong auto-match pollutes the library] → review-first default; match confidence
  threshold for the auto path decided from fixture data; Change/unmatch action.

## Migration Plan

Additive only: one alembic migration (sources + source_entitlements), no changes to
existing tables. Feature is invisible until a source is connected. Rollback = drop
the nav route; tables are inert.

## Resolved: comic-classification rule (task 1.2, finalized against fixtures)

The comic-vs-other rule, applied to a subproduct's parsed download options
(implemented in `backend/src/foragerr/sources/classify.py`, exercised by the
synthetic fixtures in `backend/tests/sources/fixtures/`):

1. Consider only download options whose Humble `platform == "ebook"` (excludes
   games, audio, software).
2. Collect each option's uppercased **format token** from its label (`name`) and
   the file extension of its signed `url.web`.
3. Any **comic-archive format** present — `CBZ` / `CBR` / `CB7` / `CBT` →
   `comic` (unambiguous signal).
4. Else a `PDF` with **no** prose format (`EPUB` / `MOBI` / `AZW3`) alongside it
   → `comic` (PDF-only OGNs / artbooks). A `PDF` shipping *with* a prose format
   → `other` (prose ebook that merely offers a PDF).
5. Everything else → `other`.

Non-comic items are stored as `other`, hidden by default and shown on demand,
never dropped — a misclassification is discoverable and reclassifiable
(FRG-SRC-003). **Preferred grabbable format** (interim: prefer CBZ, per the
format-preference direction 2026-07-11): `CBZ` → `CBR` → `CB7` → `CBT` → `PDF`;
its md5/size/filename ride on the entitlement row for the grab, with the full
option list retained in `formats_json`.

## Resolved: proposed-match ranking + auto-match threshold (worker A2)

The proposed match is computed server-side (`sources/matching.py`) by reusing
the existing relevance primitive `metadata.search.name_similarity`
(SequenceMatcher over the shared `parser.normalize.matching_key` folding,
FRG-META-015) — the same score the ComicVine search/suggest ranking sorts by.
Two candidate pools, **library-first**: the store title (issue-token and
trailing parenthetical trimmed) is ranked against the library's series; only
when no library series clears the propose floor is ComicVine consulted once
(`suggest_series`) and its top candidate proposed as an *add*. A CV budget
exhaustion (`ComicVineBudgetExhausted`, FRG-META-016) propagates so the item is
left `new` with a NULL proposal and retried next sync; CV is consulted at all
only when an api key is configured, so a batch of purchases cannot burn a path
budget. Proposals are computed in a **post-sync enrichment pass** (the
`source-sync` handler), not inside `run_sync` — keeping the diff CV-free.

The **auto-match confidence threshold** (task 3.2) is **`AUTO_MATCH_THRESHOLD =
0.85`** — the `name_similarity` value (a normalized-title SequenceMatcher ratio
in `[0,1]`) at/above which the opt-in auto-sync path may accept-and-download
without operator review. Chosen from the fixtures: `"Synthetic Hero #1"` folds
to `synthetic hero 1` and scores ~0.93 against a `"Synthetic Hero"` library
series (clears the bar), while `"...The Collected Edition Vol. 1 (collects
#1-6)"` folds to a long token run scoring well under 0.85 against the same
series (correctly withheld — a trade must never silently auto-file into the
singles run). 0.85 sits in that gap: high enough that a merely word-overlapping
different series never clears it, low enough that punctuation/casing/spacing
noise on the true title does. A separate floor `PROPOSE_MIN_SIMILARITY = 0.5`
gates whether *any* proposal is stored (a guess weaker than that is noise; the
item stays `new` with a NULL proposal, surfaced as unmatched). Below the auto
bar an item still gets a proposed match for the UI but waits for the operator.

## Resolved: owned-via-edition ownership channel (FRG-SRC-007, worker A2)

Reconciliation of a matched collected edition (`sources/reconcile.py`) makes the
singles it fills leave `wanted` through the ONLY invariant-safe channel — the
presence of an `issue_files` row (FRG-SER-019: ownership is a row's existence,
never a status/predicate). Each fillable single (one with no file of its own)
gets a `size = 0` `issue_files` row tagged with the trade `issues.id` in a new
`issue_files.edition_issue_id` column (migration 0022); an issue already owned
as a single is skipped (never replaced), and `size = 0` means the collected
file's bytes are counted once, on its own file (no double-counting). Because
ownership stays "an `issue_files` row exists", `wanted_issues()` /
`series_statistics` / the pull matcher gain NO predicate and their FRG-SER-019
absence proof is unchanged (extended by a sources-side three-way proof). Path
uniqueness moves from the column-level `UNIQUE(path)` to a **partial** unique
index over ordinary files (`edition_issue_id IS NULL`, behaviour-identical for
every scan/import file) so one collected-edition path may back several filled
singles. A trade with no declared containment (OGN/artbook) is `standalone` —
no singles are fabricated. `revert` deletes the edition rows, returning unfilled
singles to `wanted`.

## Resolved: download + failed surface (FRG-SRC-006, worker A2)

Grab (`sources/grab.py`, the `source-grab` command) re-fetches a FRESH signed
URL at grab time (`HumbleClient.fetch_download_url` — the URL is never stored),
enforces HTTPS + the `dl.humble.com` CDN host allowlist by reusing the DDL
area's `AllowList` + per-hop `hop_check` over the shared factory's `external`
profile (FRG-NFR-006), streams to `<config>/sources-staging` with the DDL
streamer's byte/size bounds, md5-verifies against the API metadata, and hands a
verified file to the EXISTING import pipeline as a normal completed download (a
`grab_history` + `import_pending` `tracked_downloads` row that
`ProcessImportsCommand` drains). *Deviation (flagged):* a grab FAILURE surfaces
on the entitlement's own `download_state = "failed"` + `download_error` axis
(retry re-queues the grab), NOT the usenet `tracked_downloads` failure loop —
that loop writes a blocklist row and auto-enqueues an indexer re-search, which
is meaningless for an account-owned store item. A checksum mismatch quarantines
the file under `sources-staging/quarantine/` (never imported).

## Open Questions

- Whether the sources hub shows a Humble "library sync" for previously-imported
  files matching entitlements (nice-to-have; default: out, revisit post-v1 of the
  screen).
