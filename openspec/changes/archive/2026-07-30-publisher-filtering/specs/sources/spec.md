# sources — delta for publisher-filtering

## MODIFIED Requirements

### Requirement: FRG-SRC-012 — Publisher classification rules

The system SHALL support an operator-managed, **library-wide** publisher
rule list that classifies matching items as non-comic at sync time,
matched on the folded publisher string (an entry ending in `*` matches as
a case-insensitive substring; every other entry matches exactly — the
trailing-`*` convention shared with the ComicVine ignore list,
FRG-META-020, though the two folds differ: classification folds with the
matching key, the ignore list casefolds, and only a **trailing** `*`
widens a classification rule). The list SHALL
apply across all sources and SHALL be managed in Settings, beside the
ComicVine ignore list — not per-source on the Sources screen. It SHALL
**ship with a curated default set** of unambiguous non-comic publisher
houses (role-playing/game and tech/textbook publishers) so a fresh install
filters common non-comic bundle content with no setup; every default entry
SHALL be operator-removable, and publishers of genuine comics are
deliberately excluded from the defaults (the recoverable-visibility rule is
the safety valve for anything over-caught). Rule changes SHALL reclassify
only rows still in the automatic classifier's hands (review state `new`);
matched and ignored rows never move. Reclassified items follow the existing
non-comic visibility rules (retained, hidden by default, never dropped).
An existing per-source rule list SHALL migrate into the library-wide list.

- **Milestone**: M6 (per-source, m6-humble-source); reshaped to
  library-wide-with-defaults in publisher-filtering.
- **Source**: mylar-feature-surface RPG-contamination handling; owner
  dogfood 2026-07-29 (empty + per-source + jargon → library-wide, seeded,
  plain-language in Settings); mirrors the curated-default posture of
  FRG-META-020.
- **Notes**: The default set is a single source-of-truth constant
  (`DEFAULT_NON_COMIC_PUBLISHERS`) referenced by the config default, the
  docs, and the tests, seeding fresh installs only — a config that already
  carries a value keeps it. Genuine-comic publishers stay off the defaults
  on the same conservative rule as FRG-META-020's reprint-house list.

#### Scenario: The list ships with removable non-comic defaults

- **WHEN** a fresh install is inspected
- **THEN** the library-wide publisher rule list carries the curated
  non-comic defaults (RPG/game and tech/textbook houses), each removable,
  and a config that already carries a value is left untouched

#### Scenario: A library-wide rule reclassifies unreviewed rows across sources

- **WHEN** the operator adds a publisher to the list and the next sync runs
- **THEN** `new` items from that publisher are classified `other` across
  every source (newly synced and previously synced alike), while matched
  or ignored items are untouched

#### Scenario: Removing a default un-filters that publisher

- **WHEN** the operator removes a default publisher (one whose books they
  do collect) and the next sync runs
- **THEN** that publisher's `new` items are classified by file shape again,
  and previously reclassified-but-unreviewed rows re-evaluate on sync

#### Scenario: Existing per-source rules migrate into the library-wide list

- **WHEN** an install that previously stored per-source publisher rules is
  upgraded
- **THEN** those rules are carried into the single library-wide list, with
  no per-source rule surface remaining
