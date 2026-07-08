# Design: m3-trade-typing (M3 change 5)

Series-level collected-edition typing. The invariant (FRG-SER-019): **no book-type
predicate ever reaches `wanted_issues()` (`library/repo.py:234`) or `series_statistics`**
— trades and singles are independent tracks, guaranteed structurally (a trade is a
separate CV volume → separate series, so its files attach to trade-line issues only).

## 1. Model

- `SeriesRow.booktype` (nullable Text) — the parser `Booktype` value lowercased
  (`tpb`/`gn`/`hc`/`one_shot`); NULL = an ordinary single-issues run. `SeriesRow.
  booktype_locked` (bool, default False) — operator override, so refresh won't
  re-derive (the FRG-SER-017 grouping-lock precedent). Both additive; must not trip
  `test_repo_hygiene`.
- Migration `0014_series_booktype`, `down_revision="0013_series_groups"`, forward-only.

## 2. Derivation

`detect_series_booktype(title) -> str | None` in `library/grouping.py` (or a new
`library/booktype.py`) reusing `parser.vocab.BOOKTYPE_CUES` / `booktype_cue_phrases`
(the same longest-first cue match the filename parser uses — `parser/result.py::Booktype`,
`parser/vocab.py`). Returns the matched book-type value or None. Pure, unit-tested. NOT
the issue-level `issue_type` vocabulary (that stays as-is); this types the *series/volume*.

## 3. Auto-derive + override

- At **add** (`library/flows/add.py`) and **refresh** (`library/flows/refresh.py`):
  when `booktype_locked` is False, set `series.booktype = detect_series_booktype(title)`.
  (Refresh does not change `series.title`, so this is stable — same reasoning as
  grouping.)
- **Override** via the series edit flow (`flows.edit_delete`, the group/aliases
  precedent): set an explicit book-type (locks it) or clear the lock (re-derive next
  refresh). Reuse the `GroupEdit`-style validated sub-object shape on `SeriesEdit`.

## 4. Non-suppression (FRG-SER-019) — the whole point

`wanted_issues()` and `series_statistics` are **not touched**. Proof obligations (tests):
1. A single-issues series with missing monitored issues (wanted) PLUS a fully-owned
   collected-edition series of the same title → every single issue stays in
   `wanted_issue_ids()`. Trades' files are on the trade series' issues; the single
   series is untouched.
2. Typing a series (auto or manual) → `wanted_issues`/`series_statistics` output is
   byte-identical before/after (same shape as the grouping non-regression test).
3. The pull matcher's existing book-type guard (`pull/matching.py:256`, on issue-level
   `issue_type`) still matches a typed line's entries — series `booktype` is a distinct
   field and does not feed that guard; a regression test pins it.

## 5. Surfacing (FRG-UI-022)

- `booktype` on `SeriesResource` (via `_series_fields`); accepted on `SeriesEdit`; an
  optional `collected` query filter on `GET /series` (booktype IS NOT NULL / IS NULL).
- Frontend: a small book-type badge (TPB/GN/HC) on `PosterCard` (library, incl. inside
  a franchise group) and the `SeriesDetail` hero; a library filter toggle
  (all / collected / singles). Display-only, Sonarr-shaped. `SeriesResource` type gains
  `booktype`.

## 6. Work-area partition (FRG-PROC-008)

- **A — backend** (`library/models.py`, migration `0014`, `library/booktype.py`,
  `flows/add.py`+`refresh.py`+`edit_delete.py`, `api/series.py`): model, detection,
  auto-derive + override, `booktype` on the resource + edit + `collected` filter, and
  the FRG-SER-019 invariant tests. SER-018, SER-019. HIGH-MEDIUM (the invariant is the
  core; prove non-suppression explicitly).
- **B — frontend** (`screens/library/`, `screens/series/`, `api/types.ts`, `store/`):
  the book-type badge + the collected filter. UI-022. Depends on A's `booktype` field.
- **C — docs/traceability/gate**: user manual (typing + badge/filter + the
  non-suppression guarantee), registry flip + matrix, review + merge + v0.3.3.

## Open Questions

None blocking. Defaults: (1) `booktype` uses the parser `Booktype` values lowercased
(consistency with existing evidence/naming), null for single-issues. (2) The library
`collected` filter is a simple all/collected/singles toggle, not per-subtype. (3)
`one_shot` is derived if the cue is present but shown without a badge subtype unless it
reads naturally (implementer's call) — the binary collected-vs-single is what matters.
