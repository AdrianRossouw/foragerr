# Design — m4-add-new

## Context

The Add New screen (`frontend/src/screens/add/AddSeries.tsx`, 604 lines) is
functionally complete — root folders, format profiles, monitor strategies,
search-on-add, autosuggest, URL/id paste, and the full outcome-state matrix
all exist and are well tested (911-line test file). Two things are wrong with
it: it predates the M4 design language, and lookup results render in
ComicVine's raw `name:asc` alphabetical order — the plausibility signals we
compute per candidate (`metadata/search.py`) are shown as chips but never
influence order, an explicit M1 stance recorded in FRG-META-007's notes.
Design reference: the handoff's `screens/add-new.png` + prototype logic
(extracted in the session scratchpad under `design/design_handoff_foragerr_app/`).

## Goals / Non-Goals

**Goals:**

- Rebuild the screen's presentation to the design handoff (expandable result
  cards, inline add-config panel, monitor segmented control, collect-as).
- Server-side relevance ordering (FRG-META-015), identical for lookup and
  suggest.
- Optional add-time book-type override wired into FRG-SER-018's lock
  mechanics.

**Non-Goals:**

- No new quality-profile concept; no results sort/filter UI; no changes to
  release/download search; no publisher hard-filtering beyond the ignore list.

## Decisions

1. **Rank in the API layer, after annotation, not in the ComicVine client.**
   `search_series()`/`suggest_series()` keep fetching with `sort=name:asc`
   (stable upstream pagination); the ordering is applied where plausibility is
   computed, on the assembled candidate list, so both endpoints share one
   sort function. Sort key: `(-name_similarity, year_distance, upstream_index)`
   — `upstream_index` makes the sort stable and total, so equal-signal
   candidates keep CV's order and pagination/caps behave unchanged.
   Alternative rejected: client-side sorting in React (would let lookup and
   suggest drift and leaves the API contract "unordered").
2. **No new response fields.** The signals already ship on candidates; order
   itself is the new information. Frontend must render API order untouched.
3. **Collect-as maps to the existing booktype/lock model** (FRG-SER-018), not
   a new concept: `SeriesCreate` gains optional `booktype` (vocabulary value
   or explicit `"none"` for single issues); present → persist locked, skip
   derivation; absent → derive as today. UI control is the design's two-way
   segmented (Single Issues / Collected Editions) with **no selection by
   default** (derivation); Collected Editions sends `tpb` — the common case —
   refinable to gn/hc on the series afterward. Deviating slightly from the
   mock (which implies a always-selected control) keeps untouched-add behavior
   byte-identical to today.
4. **Rebuild presentation, keep the machinery.** Hooks (`useSuggest`,
   `useRootFolders`, `useFormatProfiles`, `useAddSeries`), outcome-state
   logic, and `normalizeLookupTerm` survive; card/panel markup is rebuilt to
   the handoff (tokens already in the app shell from ch1). Plausibility chips
   are retired from the card face (ranked order + "In library" badge replace
   them); the deck/description comes from the candidate payload's existing
   description field.
5. **Screenshot refresh runs against a dedicated clean instance** — never the
   operator's :8790 demo (owner instruction 2026-07-11: it is polluted by
   real browsing and copyrighted content). Verify
   `tools/refresh-readme-shots.sh` spins its own instance (own port, fresh
   DB, public-domain seed) per FRG-PROC-017's wording; if it targets a
   running instance instead, fix it in this change.

## Risks / Trade-offs

- [Ranking makes some obscure searches *feel* worse (similarity on short
  generic terms is noisy)] → stable sort + signals still visible; the corpus
  test pins known searches ("Saga", "Immortal Thor") to sane top results.
- [Suggest endpoint is first-page-only; ranking within one CV page can't
  surface a match CV paginates away] → accepted, unchanged from today;
  full lookup remains the authoritative path.
- [Collected Editions → `tpb` is lossy vs gn/hc] → documented simplification;
  series edit already offers the full vocabulary (FRG-SER-018).
- [Frontend rebuild regresses a tested outcome state] → the 911-line test
  suite is reworked, not discarded; every outcome-state scenario in FRG-UI-005
  keeps a test.

## Migration Plan

Single change branch `change/m4-add-new`; no schema migration (`booktype` /
`booktype_locked` exist since migration 0014). Rollback = revert merge.

## Open Questions

_None — scope decisions were made at proposal approval (full scope)._
