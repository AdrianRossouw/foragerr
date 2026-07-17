# opds — m9-opds-per-issue-cover deltas

## ADDED Requirements

### Requirement: FRG-OPDS-020 — Per-issue cover on issue entries; series cover on the shelf

Each OPDS acquisition (issue) entry SHALL advertise its own issue-file cover — the first-page render addressed by that file's id — so every issue in a series renders with a distinct cover that matches the page the reader opens to, never a single series-level image repeated across issues. The one cached series-level ComicVine cover SHALL instead be advertised on the series navigation entry (the All Series shelf and search results), and only when a cover is cached.

- **Milestone**: M9 (m9-opds-per-issue-cover)
- **Source**: On-device Panels couch test 2026-07-17 — all issues of a series showed the same cover, mismatched to each issue's first page.
- **Notes**: A comic's first page is its cover, so the per-issue-file render (FRG-OPDS-011) is the correct per-issue image; the ComicVine volume cover (one image per series) belongs at the series/shelf level. Both cover routes are on the OPDS realm (FRG-OPDS-019). No per-issue ComicVine cover art is cached; the first-page render is the per-issue source.

#### Scenario: Distinct per-issue covers in an acquisition feed

- **WHEN** a series with multiple issue-files (and a cached series cover) is rendered as an acquisition feed
- **THEN** each entry's image and thumbnail links address that entry's own issue-file cover render, and no two entries share one series-level cover URL

#### Scenario: Series cover on the shelf, only when cached

- **WHEN** the All Series shelf (or a search feed) renders a series that has a cached cover, and separately one that does not
- **THEN** the cached-cover series' navigation entry carries a series-level image/thumbnail link while the uncached series' entry carries none
