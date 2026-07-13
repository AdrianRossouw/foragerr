import {
  ToolbarButton,
  ToolbarSeparator,
  GridIcon,
  SlidersIcon,
  SortIcon,
  FilterIcon,
} from 'foragerr-frontend';

/** A realistic library-toolbar cluster, mirroring LibraryIndex's usage. */
export const ToolbarGroup = () => (
  <div style={{ display: 'flex', alignItems: 'center' }}>
    <ToolbarButton icon={<GridIcon size={16} />} label="Grid" onClick={() => {}} active />
    <ToolbarSeparator />
    <ToolbarButton icon={<SlidersIcon size={16} />} label="Options" onClick={() => {}} />
    <ToolbarButton icon={<SortIcon size={16} />} label="Sort" onClick={() => {}} />
    <ToolbarButton icon={<FilterIcon size={16} />} label="Filter" onClick={() => {}} />
  </div>
);

/** Disabled state, dimmed against an active sibling. */
export const DisabledVsActive = () => (
  <div style={{ display: 'flex', alignItems: 'center' }}>
    <ToolbarButton icon={<SortIcon size={16} />} label="Sort" onClick={() => {}} active />
    <ToolbarButton icon={<FilterIcon size={16} />} label="Filter" onClick={() => {}} disabled />
  </div>
);
