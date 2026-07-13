import { ToolbarButton, ToolbarSeparator, GridIcon, SortIcon } from 'foragerr-frontend';

/** The separator between logical toolbar button groups, shown in situ. */
export const InContext = () => (
  <div style={{ display: 'flex', alignItems: 'center' }}>
    <ToolbarButton icon={<GridIcon size={16} />} label="Grid" onClick={() => {}} active />
    <ToolbarSeparator />
    <ToolbarButton icon={<SortIcon size={16} />} label="Sort" onClick={() => {}} />
  </div>
);
