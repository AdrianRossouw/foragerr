# ui delta — m4-library-views

## MODIFIED Requirements

### Requirement: FRG-UI-003 — Library index screen

The UI SHALL provide a library index screen listing all series in three view
modes: **Posters** — a responsive `auto-fill` grid with selectable poster
sizes (S/M/L ≈ 134/162/196px), each card a 2:3 cover with a monitored
bookmark chip, publisher and volume chips, an owned/total progress strip
(track color reflecting complete vs incomplete, accent fill), and title +
subline; **Overview** — horizontal rows with cover thumb, title, status pill,
publisher/meta, a wide progress bar and percent complete; **Table** — a dense
table with monitor icon, Title (+volume), Publisher, Issues (mini progress),
Status, and Year columns. Above the content a count line SHALL read
`N comics · N monitored · N with missing issues` with the monitored and
missing counts in their semantic colors. The toolbar SHALL carry the view
switcher and three dropdown menus in the design's raised-menu style —
**Options** (poster-size segmented control, group-volumes toggle), **Sort**
(Title, Publisher, Issues owned, Year; check mark on the active choice), and
**Filter** (All, Monitored, Missing issues, Continuing; each option showing
its count) — plus a text filter; a click in the content region SHALL close
any open menu. View mode, poster size, sort, and filter selections SHALL
persist across sessions.

- **Milestone**: M1 (redesigned to the owner's design in M4, m4-library-views)
- **Source**: sonarr-architecture.md §7.4 (Series index); mylar-feature-surface.md UI section; owner design handoff (library screen, options/sort/filter menus), reviewed 2026-07-10.
- **Notes**: "UI browse" leg of the vertical slice. The M4 redesign supersedes the M1 visual language; behavior (local covers only, detail navigation, filtering semantics) is unchanged. Publisher tints/accents come from the ch1 palette maps.

#### Scenario: Poster grid renders from local cover endpoint

- **WHEN** the index renders a mocked library of 50+ series in poster mode
- **THEN** each card shows the title, monitored bookmark, publisher chip, and owned/total progress strip, and every poster `img` `src` points at the local cover endpoint (no external ComicVine image host)

#### Scenario: View-mode switcher covers all three modes

- **WHEN** the user cycles the view switcher through Posters, Overview, and Table
- **THEN** the same series render as poster cards, overview rows, and dense table rows respectively, and returning to a mode restores its layout

#### Scenario: Poster size control

- **WHEN** the user selects S, M, or L in the Options menu
- **THEN** the poster grid re-lays out at the corresponding card size and the choice persists across a reload

#### Scenario: Sort and filter menus drive the list

- **WHEN** the user picks a Sort option and a Filter option, and types a substring into the text filter
- **THEN** the rendered order matches the sort, only series meeting the filter (and substring) remain, the active sort shows its check mark, and each filter option displays its live count

#### Scenario: Count line reflects the library

- **WHEN** the index renders
- **THEN** the count line shows total, monitored (accent), and with-missing-issues (warn) counts consistent with the rendered library

#### Scenario: Menus close on content interaction

- **WHEN** a toolbar menu is open and the user clicks in the content region
- **THEN** the menu closes without activating content beneath it unexpectedly

#### Scenario: Selecting a series opens detail

- **WHEN** the user clicks a series card, overview row, or table row
- **THEN** the series-detail screen opens for that series

### Requirement: FRG-UI-021 — Grouped library view

The Comics (library index) screen SHALL offer a **grouped** display mode alongside the
poster/overview/table modes: in poster mode, a franchise's volumes SHALL stack into a
single card with a layered offset-shadow treatment and an `N vols` chip, the progress
strip showing summed owned/total across members; in row/table contexts franchise
groups render as headers carrying the group title and an aggregated stat roll-up,
with their member runs nested beneath and collapsible. A franchise with a single run
SHALL render as an ordinary card/row (no group chrome). The mode SHALL be the
group-volumes toggle in the Options menu; switching it SHALL not change series
identity, monitoring, or any per-series action, and the flat views SHALL remain
available and unchanged. From the grouped view the operator SHALL be able to reach
the group rename / series-reassign affordance (FRG-SER-017).

#### Scenario: Grouped posters stack into one card

- **WHEN** the operator enables group-volumes in poster mode with a multi-volume franchise present
- **THEN** the franchise renders as one stacked card with the layered shadow, an `N vols` chip, and summed owned/total on the progress strip, while single-run franchises render as ordinary cards

#### Scenario: Grouped mode nests runs under franchise headers

- **WHEN** the operator switches to grouped mode in a row/table context with multiple runs of one title
- **THEN** the runs appear nested under one collapsible franchise header with a roll-up stat, and single-run franchises render as ordinary rows

#### Scenario: Grouping is display-only

- **WHEN** the grouped view is shown
- **THEN** per-series monitored state, actions, and navigation behave exactly as in the flat views, and toggling back to a flat view shows the same series unchanged

#### Scenario: Correcting a group from the view

- **WHEN** the operator renames a group or reassigns a run from the grouped view
- **THEN** the change takes effect through the existing FRG-SER-017 affordance exactly as before the redesign
