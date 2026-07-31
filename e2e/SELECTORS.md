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
| `ft-rejections-<guid>` | verbatim rejection-reason `<ul>` inside the interactive-search popover (`ReasonsPopover.tsx`, rendered by `InteractiveSearchOverlay.tsx`) | the reasons are otherwise unlabelled `<li>`s nested in a popover; the harness reads them to assert verbatim rendering (FRG-UI-007) |
| `ft-manual-rejections-<name>` | verbatim rejection-reason `<ul>` inside the manual-import popover (`ReasonsPopover.tsx`, rendered by `ManualImportOverlay.tsx`) | same shape as `ft-rejections`, keyed by candidate file name; the harness reads it to assert a blocked file's verbatim reasons (FRG-UI-014) |

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
- **Queue** (`/queue`): `queue-row-<id>`; `queue-progress-<id>` (absent on a
  failed row, which renders no progress); an `import_blocked` row's button
  "Manual import \<title\>"; `queue-table-wrap`; per-row checkbox
  "Select \<title\>", header checkbox "Select all queue items",
  `queue-selection-count` and button "Remove selected"; per-row button
  "Remove \<title\>"; toolbar button "Clear failed".
- **Manual-import overlay** (`ManualImportOverlay.tsx`): `manual-row-<name>`;
  per-row checkbox "Select \<name\>", comboboxes "Series/Issue/Format for
  \<name\>"; the rejection chip (opens the popover carrying
  `ft-manual-rejections-<name>`); `manual-embedded-<name>`; footer
  `manual-command-status`, `manual-import-error`, `manual-import-confirm`.
- **Library index** (`/`): series links by title; `library-poster-grid` /
  `library-table`; `series-read-only-<seriesId>` marker chip.
- **Settings → indexers** (`/settings/indexers`): `provider-card-<id>`, button
  "Edit \<name\>".
- **Settings → media management** (`/settings/media-management`):
  `root-folders-section`, `root-folder-<id>`, `root-folder-read-only-<id>`.
- **Read-only treatment** (FRG-UI-045): `add-read-only-note` on the add-options
  panel; `series-read-only-badge` on series detail, where the suppressed
  affordances are asserted by ABSENCE of their accessible names (buttons
  "Search Monitored" / "Search All" / "Edit", menu item "Rename Files",
  per-issue "Interactive search for issue \<n\>", the delete dialog's
  "Also delete files from disk" checkbox).
- **OPDS** (server-rendered, no testids): `/opds`, `/opds/series`,
  `/opds/series/<id>`, `/opds/file/<issueFileId>`.
