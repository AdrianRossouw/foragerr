## Why

The final M3 comics-native gap is **collected editions** (trades/TPBs). In ComicVine a
trade line is its own volume — "Saga: Deluxe Edition", "Batman: The Long Halloween
(TPB)" — so foragerr already stores it as an ordinary `SeriesRow`. But nothing marks it
as a *collected* series, so a trade line looks identical to a single-issues run in the
library, in naming, and to the operator's eye.

The load-bearing rule (Adrian, 2026-07-05, and the reason this is its own change):
**owning a trade must NEVER suppress single-issue wanted state.** Singles and trades
are independent acquisition tracks — you can want every single issue of "Saga" AND own
the deluxe hardcover, and the single issues stay wanted, missing, and searchable. The
good news the architecture already gives us: because a trade is a *separate* CV
volume → separate series, its files attach to trade-line issues and can never create a
file on a single-issue row, and the one derived-wanted choke point (`wanted_issues()`)
has no book-type predicate. This change adds the **type** (so trades are labelled and
named as trades) while making the non-suppression invariant an explicit, tested
requirement — not a naive book-type filter bolted onto the wanted query.

## What Changes

- **Series collected-edition typing (FRG-SER-018, NEW)** — a series gains a nullable
  `booktype` (the existing parser `Booktype` vocabulary: `tpb`/`gn`/`hc`/`one_shot`;
  null = an ordinary single-issues run) plus a `booktype_locked` override flag. It is
  **auto-derived** from the series title at add and refresh using the existing
  `BOOKTYPE_CUES` (the same cues the filename parser uses — "TPB", "graphic novel",
  "hardcover"…), and the operator can set it explicitly (locked so refresh won't
  re-derive), mirroring the grouping-override precedent (FRG-SER-017). A typed series is
  labelled and, where naming templates use `{Booktype}`, named as its type; a
  collected series' single-issue-vs-trade nature is now visible in the library and
  detail views.

- **Trades never suppress single-issue wanted (FRG-SER-019, NEW)** — a first-class,
  **tested** invariant: a series' collected-edition typing (and owning a full trade
  line) SHALL NOT remove, hide, or de-prioritise any single issue from
  wanted/missing/searchable state. Singles and trades are independent tracks. This is
  enforced structurally — no book-type predicate reaches `wanted_issues()` or
  `series_statistics`, and a trade's files attach only to its own trade-line issues —
  and proven by dedicated tests (a fully-owned trade line leaves every single issue of
  the same title still wanted; the pull matcher's existing book-type guard still
  matches a typed line's entries).

- **Collected-edition surfacing (FRG-UI-022, NEW)** — a **collected-edition badge**
  (TPB/GN/HC) on the series card in the library (including within a franchise group,
  change 4) and on the series-detail hero, plus a library filter to show/hide collected
  editions. Display-only; every per-series action and the wanted machinery are
  unchanged.

## Capabilities

### New Capabilities

- `ser`: FRG-SER-018 (collected-edition typing), FRG-SER-019 (trades never suppress
  single-issue wanted).
- `ui`: FRG-UI-022 (collected-edition surfacing).

## Impact

- **Code**: backend + frontend. `SeriesRow.booktype` (nullable) + `booktype_locked`
  columns under a forward-only migration `0014`; a `detect_series_booktype(title)`
  helper reusing `parser.vocab.BOOKTYPE_CUES`; auto-derivation wired into the add and
  refresh flows (skipped when locked); the series edit flow gains a book-type override
  (the `aliases`/group-override precedent); `booktype` exposed on `SeriesResource` and
  accepted on `SeriesEdit`; an optional `collected` filter on `GET /series`. Frontend: a
  badge on the series card + detail hero, a collected-editions filter, and the type
  field on the series type. **`wanted_issues()` and `series_statistics` are NOT
  touched** (the invariant).

- **DB**: two additive nullable/defaulted columns on `series` under migration `0014`
  (rides FRG-DB-002/008; no DB *requirement* change). Must not trip the schema-hygiene
  test.

- **Security** (FRG-PROC-006): **none.** No new listener, untrusted-input parser,
  credential, or outbound integration — typing derives from existing local title text.

- **Manual** (FRG-PROC-011): **user-facing.** `docs/manual/user/` (library section)
  documents collected-edition typing, the badge/filter, and — prominently — that
  owning a trade never affects single-issue wanted state.

- **Dependencies / SOUP** (FRG-PROC-012): **none.**

## Non-goals

- **No trade→single "collected in" containment linkage.** Showing which single issues a
  trade collects is an informational badge deferred to backlog (owner decision
  2026-07-05); it needs overlap data ComicVine does not reliably provide in the mapped
  fields. This change types the trade *line*, not its contents.

- **No book-type-aware search release filter.** Making a collected series search only
  for trade releases (and a single-issues series only for single releases) is a search
  refinement left to a later change; the search decision engine is untouched here, so
  typing changes no acquisition behavior beyond labelling/naming.

- **No auto-add of trade lines, and no change to wanted/monitoring.** Typing never
  monitors, wants, un-wants, or adds anything. The non-suppression invariant is the
  whole point.

- **No trade-specific folder layout.** Naming already emits a `{Booktype}` token from
  filename evidence; a series-typed *default* naming beyond that is out of scope.

## Approval

Pre-approved under the standing M2/M3 FRG-PROC-009 grant (2026-07-06); Adrian directed
"do 4 + 5" on 2026-07-08. The never-suppress-single-issue-wanted rule is his explicit
2026-07-05 decision, here promoted to a dedicated tested requirement (FRG-SER-019).
Built in the current Sonarr-shaped style; a later design-milestone restyle (the parked
`Foragerr.dc.html` mockup sketches a Collections treatment) is out of scope. Recorded
per the standing-grant model used across M2/M3.
