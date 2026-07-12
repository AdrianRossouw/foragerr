import { Toolbar, ToolbarButton, ToolbarSeparator, RefreshIcon, ImportIcon, GridIcon, TableIcon, SortIcon } from 'foragerr-frontend';

/** Library page toolbar: title, page actions, view-mode toggle (active = accent). */
export const LibraryToolbar = () => (
  <Toolbar
    title="Comics"
    actions={
      <>
        <ToolbarButton icon={<RefreshIcon />} label="Refresh" onClick={() => {}} />
        <ToolbarButton icon={<ImportIcon />} label="Import" onClick={() => {}} />
        <ToolbarSeparator />
        <ToolbarButton icon={<GridIcon />} label="Posters" active onClick={() => {}} />
        <ToolbarButton icon={<TableIcon />} label="Table" onClick={() => {}} />
      </>
    }
  />
);

/** Title-only toolbar (pages with no actions yet). */
export const TitleOnly = () => <Toolbar title="Calendar" />;

/** Disabled action state (e.g. refresh already running). */
export const DisabledAction = () => (
  <Toolbar
    title="Wanted"
    actions={
      <>
        <ToolbarButton icon={<RefreshIcon />} label="Refresh" disabled onClick={() => {}} />
        <ToolbarButton icon={<SortIcon />} label="Sort" onClick={() => {}} />
      </>
    }
  />
);
