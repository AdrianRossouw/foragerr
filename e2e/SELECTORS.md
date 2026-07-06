# e2e selector contract (`ft-*` data-testids)

The Playwright spine selects on stable **`data-testid`** hooks and accessible
names (`aria-label` / role / heading text), never on CSS classes or incidental
text. Frontend components already expose most of what the harness needs; the
`ft-*` namespace is reserved for hooks added specifically for e2e where
text/role selection is brittle (FRG-PROC-010, design decision 4).

## `ft-*` hooks owned by the harness

| testid | element | why it exists |
| --- | --- | --- |
| `ft-add-confirm` | add-series confirm button (`AddSeries.tsx`) | its visible label is the dynamic series name (`Add Saga`), so text selection is unstable |
| `ft-rejections-<guid>` | verbatim rejection-reason `<ul>` inside the interactive-search popover (`InteractiveSearchOverlay.tsx`) | the reasons are otherwise unlabelled `<li>`s nested in a popover; the harness reads them to assert verbatim rendering (FRG-UI-007) |

Keep this list minimal. Prefer an existing hook or an accessible name before
adding a new `ft-*` id.

## Existing selectors the spine relies on

These already exist in the frontend and are treated as a contract by the suite:

- **Add series** (`/add`): `searchbox` "Search ComicVine"; submit button
  "Search"; `candidate-<cvVolumeId>` cards; button "Select \<name\>";
  `add-options-panel`; comboboxes "Root folder" / "Format profile".
- **Series detail** (`/series/:id`): `issue-row-<issueId>`; per-row button
  "Interactive search for issue \<n\>"; `interactive-search-overlay`;
  `command-status`.
- **Interactive search overlay**: `release-row-<guid>`; button "Grab \<title\>";
  the rejection chip (opens the popover carrying `ft-rejections-<guid>`).
- **Queue** (`/queue`): `queue-row-<id>`; `queue-progress-<id>`.
- **Library index** (`/`): series links by title; `library-poster-grid` /
  `library-table`.
- **Settings → indexers** (`/settings/indexers`): `provider-card-<id>`, button
  "Edit \<name\>".
- **OPDS** (server-rendered, no testids): `/opds`, `/opds/series`,
  `/opds/series/<id>`, `/opds/file/<issueFileId>`.
