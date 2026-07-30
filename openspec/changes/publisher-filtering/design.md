# publisher-filtering — design

## Context

Two publisher-filtering controls exist today:
- **CV ignore list** (`DEFAULT_IGNORED_PUBLISHERS`, FRG-META-020) —
  library-wide, in Settings, ships prepopulated with reprint houses,
  filters ComicVine *search* results.
- **Per-source publisher rules** (FRG-SRC-012) — stored in each source's
  encrypted settings envelope, edited on the Sources screen
  (`PublisherRules.tsx` in `StoreManage`), ships **empty**, classifies
  Humble items as non-comic at sync (`sources/classify.py`).

The owner's feedback targets the second: empty, per-source-on-Sources,
jargon copy. The fix makes it look like the first — library-wide, in
Settings, seeded — for the classification axis.

## Goals / Non-Goals

**Goal**: one library-wide, Settings-based, seeded, plain-language
non-comic publisher filter. **Non-goals**: deeper metadata-based
classification (finding #7), unifying with the CV *search* ignore list,
per-source overrides.

## Decisions

**D1 — Rules move from per-source envelope to a library-wide config
value.** A new `DEFAULT_NON_COMIC_PUBLISHERS` constant (same shape and
`*`-substring semantics as `DEFAULT_IGNORED_PUBLISHERS`) seeds a
library-wide setting; `sources/classify.py` reads it instead of the
per-source list. Rationale: the owner runs one source and thinks
library-wide; per-source granularity was speculative and is the source of
the "why is this on the Sources screen" confusion. Alternative — keep
per-source but seed each with defaults — rejected: it multiplies the
setup surface the feedback is about and keeps the odd placement.

**D2 — Ship a conservative, removable default set.** RPG/game houses
(Paizo, Pelgrane, Green Ronin, Kobold, Free League, Modiphius, …) and
tech/textbook houses (O'Reilly, No Starch, Manning, Packt, Pragmatic
Bookshelf, …) — houses whose Humble output is overwhelmingly non-comic.
Genuine-comic publishers stay off, same rule as FRG-META-020. Every entry
is operator-removable ("others might buy them"), and the recoverable
non-comic visibility (retained, hideable, never dropped) is the safety
valve. Seeds fresh installs only; an existing config value is kept.

**D3 — Migrate existing per-source rules into the library-wide list.**
On upgrade, union any per-source `publisher_rules` from every source's
settings envelope into the new library-wide value (then the per-source
field is unused). One-time and idempotent, as a startup hook rather than
the config-file migration path: the union needs the database and the
keystore (to read source envelopes), which the config layer predates, and
it must complete before the scheduler can dispatch any sync so the first
post-upgrade classification already sees the carried rules. Union
fidelity rules: comma-bearing stored entries flatten to spaces
(fold-neutral), a wildcard spelling survives a folded-key collision with
an exact one, the union bases on the on-disk config (a restored backup is
never clobbered), and a hook failure logs and defers to the next boot
instead of blocking startup. Rationale: silently losing or narrowing an
operator's stored rules would be a regression.

**D4 — Plain UI copy, Settings home.** The panel moves from `StoreManage`
to Settings beside the ignore-list control; the "RPG-sourcebook escape
hatch" text becomes a user-facing description naming the real cases (RPG,
tech books, art books) without implementation framing.

## Risks / Trade-offs

- [Shipping a non-empty default reclassifies content on fresh installs
  (intent-presuming default)] → owner-directed; every default removable;
  reclassification is non-destructive (retained + recoverable), and only
  affects `new` rows, never a reviewed decision.
- [A default over-catches a publisher someone does collect] → removable +
  recoverable; conservative curation keeps genuine-comic houses off.
- [Migration union across many source envelopes] → bounded (few sources);
  a source that fails to decrypt contributes nothing rather than aborting
  the migration.

## Migration Plan

Carry existing per-source `publisher_rules` into the new library-wide
config value (union, deduped case-insensitively), one-time on upgrade.
The library-wide value seeds from `DEFAULT_NON_COMIC_PUBLISHERS` only when
absent. No schema table change beyond the config value; rollback = revert
(the per-source field still exists, just unused).

## Open Questions

- Final default publisher set — the constant above is a starting curation;
  worth a quick owner pass before it ships, since a bad default is the
  same over-catch risk FRG-META-020 guards against.
- Whether to visually distinguish shipped defaults from operator-added
  entries in the panel (nice-to-have, not required).

## Deferred follow-ups (recorded at the merge gate)

- **publisher-list-unification** (one future change): a shared
  publisher-match-list module parameterized by fold and wildcard policy,
  adopted by both the ComicVine ignore list and the classification rules
  (today they are deliberately different folds with near-identical
  shapes); one shared rule-identity/normalize helper with a collision
  policy (the config validator keeps `Paizo` + `Paizo*` distinct while
  the migration union prefers the wildcard — both defensible, currently
  re-derived); server-side enforcement that only a trailing `*` widens a
  rule (today interior-`*` entries are inert and only the panel refuses
  them); a shared frontend publisher-list editor for both Settings
  fields; bounds on `comicvine_ignored_publishers` matching the new
  list's validator.
- The `hidden` schema flag hides a field from the rendered connect form
  only; the general form (public_settings omission + write-path
  rejection as one contract) is part of the unification follow-up. The
  write path itself is already closed (connect/reconnect strip the
  field).
- Startup migration reads every source envelope each boot until rules
  are cleared; a completion marker would short-circuit it (bounded by
  source count, low priority).
