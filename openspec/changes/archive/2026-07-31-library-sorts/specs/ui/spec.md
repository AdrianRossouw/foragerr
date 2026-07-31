# ui — delta for library-sorts

## MODIFIED Requirements

### Requirement: FRG-UI-003 — Library index screen

The UI SHALL provide a library index screen listing all series in three view
modes: **Posters** — a responsive `auto-fill` grid with selectable poster
sizes (S/M/L ≈ 134/162/196px), each card a 2:3 cover with a monitored
bookmark chip, a publisher chip, the book-type badge where typed
(FRG-UI-022), an owned/total progress strip (track color reflecting complete
vs incomplete, accent fill), and title + status/year subline (an `N vols`
chip appears on the grouped stacked card only — FRG-UI-021); **Overview** —
horizontal rows with cover thumb, title, status pill, publisher/meta, a wide
progress bar and percent complete; **Table** — a dense table with monitor
icon, Title (+ book-type badge), Publisher, Issues (mini progress), Status,
and Year columns. Above the content a count line SHALL read
`N comics · N monitored · N with missing issues` with the monitored and
missing counts in their semantic colors. The toolbar SHALL carry the view
switcher and three dropdown menus in the design's raised-menu style —
**Options** (poster-size segmented control, group-volumes toggle), **Sort**
(Title, Publisher, Issues owned, Year, Size on disk, Latest issue; check
mark on the active choice; Size on disk orders by the series' aggregate
file bytes descending, Latest issue by the most recent known release date
descending with undated series last, both tiebreaking on title;
sorting applies to the flat views, so the menu is disabled while grouping is
on), and **Filter** (All, Monitored, Missing issues, Continuing; each option
showing its count; plus an EDITIONS section carrying the FRG-UI-022
collected-editions filter with counts) — plus a text filter; a click in the
content region SHALL close any open menu without activating the content
beneath it. View mode, poster size, sort, and filter selections SHALL
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


#### Scenario: Size and recency sorts order by the stored statistics

- **WHEN** the user picks Size on disk, then Latest issue
- **THEN** the flat views order by the series statistics' size-on-disk
  (largest first), then by the most recent known release date (newest
  first, undated series after all dated ones), each choice shows its
  check mark and persists across a reload, and no additional requests
  are made (the statistics already ride the index payload)
