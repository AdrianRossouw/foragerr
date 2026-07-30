# ui — delta for publisher-filtering

## ADDED Requirements

### Requirement: FRG-UI-046 — Publisher-filtering settings panel

The UI SHALL present the library-wide publisher classification rules
(FRG-SRC-012) as a Settings panel beside the ComicVine ignore-list
control, showing the current list (defaults included) with add and remove,
and SHALL NOT surface the rules per-source on the Sources screen. The
panel's language SHALL be user-facing and plain — describing that some
bundle items are not comics (for example RPG rulebooks, tech-book PDFs, or
art books) and that listing their publishers files them as Other whatever
the file type — and SHALL NOT expose implementation framing (no "escape
hatch," no single-genre assumption). It SHALL state that changes take
effect on the next sync and do not move already-reviewed items.

- **Milestone**: publisher-filtering.
- **Source**: owner dogfood 2026-07-29 (the panel felt empty, misplaced on
  the Sources screen, and its "RPG-sourcebook escape hatch" copy leaked
  implementation context).
- **Notes**: Replaces the per-source `PublisherRules` panel in
  `StoreManage`. The safety story (recoverable, next-sync, sticky decisions)
  stays; only the wording is de-jargoned and the home is Settings.

#### Scenario: The rules live in Settings with plain language

- **WHEN** the operator opens Settings
- **THEN** the publisher-filtering panel shows the current list (with its
  defaults), offers add/remove, describes non-comic filtering in plain
  user terms with no implementation jargon, and no publisher-rules control
  appears on the Sources screen

#### Scenario: Editing the list is explicit and reversible

- **WHEN** the operator removes a default or adds a publisher
- **THEN** the change is shown in the list and takes effect on the next
  sync, and the panel states that already-matched or -ignored items are
  not moved
