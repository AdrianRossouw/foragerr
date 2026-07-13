import type { SVGProps } from 'react';

/*
 * Minimal inline SVG icon set (no icon-library dependency). All icons draw in
 * `currentColor` so color comes entirely from the token-driven CSS around
 * them, and size via the CSS `--icon-size-*` tokens (default md).
 */

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Svg({ size = 18, children, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  );
}

export function LogoMarkIcon({ size = 20, ...rest }: IconProps) {
  /* The forager ant in a comic speech bubble (owner-selected 2026-07-13 from
   * the Claude Design logo iterations, variant "appmarkant"). Drawn entirely
   * in currentColor so the lockup colors it via CSS; renders on the chrome
   * with no tile behind it. */
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      fill="none"
      overflow="visible"
      aria-hidden
      focusable="false"
      {...rest}
    >
      <path d="M30 68 L20 86 L44 72 Z" fill="currentColor" />
      <rect
        x={12}
        y={12}
        width={76}
        height={60}
        rx={26}
        stroke="currentColor"
        strokeWidth={6.5}
      />
      <ellipse cx={35} cy={48} rx={15} ry={11.5} fill="currentColor" />
      <circle cx={49} cy={48} r={3.2} fill="currentColor" />
      <ellipse cx={57} cy={46} rx={8} ry={7} fill="currentColor" />
      <circle cx={70} cy={43} r={10} fill="currentColor" />
      <path d="M79 44 l6 2 l-6 2.5 Z" fill="currentColor" />
      <g stroke="currentColor" strokeWidth={4} strokeLinecap="round">
        <path d="M76 35 Q86 26 82 18" />
        <path d="M79 37 Q90 30 89 22" />
      </g>
      <g
        stroke="currentColor"
        strokeWidth={4.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M47 53 L42 68 L35 76" />
        <path d="M55 53 L53 70 L47 78" />
        <path d="M61 52 L67 68 L71 78" />
      </g>
    </svg>
  );
}

/** Sonarr-style monitor bookmark; filled when active. */
export function BookmarkIcon({
  filled = false,
  ...rest
}: IconProps & { filled?: boolean }) {
  return (
    <Svg {...rest} fill={filled ? 'currentColor' : 'none'}>
      <path d="M6 3h12v18l-6-4.5L6 21z" />
    </Svg>
  );
}

export function GridIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="3" y="3" width="7" height="7" />
      <rect x="14" y="3" width="7" height="7" />
      <rect x="3" y="14" width="7" height="7" />
      <rect x="14" y="14" width="7" height="7" />
    </Svg>
  );
}

export function TableIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="3" y="4" width="18" height="16" rx="1" />
      <line x1="3" y1="9" x2="21" y2="9" />
      <line x1="3" y1="14" x2="21" y2="14" />
      <line x1="10" y1="9" x2="10" y2="20" />
    </Svg>
  );
}

/** Horizontal rows = the Overview (list) view. */
export function RowsIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="3" y="4" width="18" height="5" rx="1" />
      <rect x="3" y="13" width="18" height="5" rx="1" />
    </Svg>
  );
}

/** Sliders = the Options menu. */
export function SlidersIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <line x1="4" y1="8" x2="20" y2="8" />
      <circle cx="9" cy="8" r="2" fill="currentColor" />
      <line x1="4" y1="16" x2="20" y2="16" />
      <circle cx="15" cy="16" r="2" fill="currentColor" />
    </Svg>
  );
}

/** Descending sort bars = the Sort menu. */
export function SortIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <line x1="4" y1="6" x2="13" y2="6" />
      <line x1="4" y1="12" x2="10" y2="12" />
      <line x1="4" y1="18" x2="7" y2="18" />
      <path d="M17 4v14" />
      <path d="M14 15l3 3 3-3" />
    </Svg>
  );
}

/** Funnel = the Filter menu. */
export function FilterIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 5h16l-6 8v6l-4-2v-4z" />
    </Svg>
  );
}

/** Check mark = the active option in a Sort/Filter menu. */
export function CheckIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M5 12l5 5L20 7" />
    </Svg>
  );
}

/** Stacked layers = the grouped-franchise `N vols` chip (FRG-UI-021). */
export function LayersIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 3l9 5-9 5-9-5z" />
      <path d="M3 13l9 5 9-5" />
    </Svg>
  );
}

/** Open book = the empty-library / no-match placeholder (FRG-UI-003). */
export function BookOpenIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 6c-1.8-1.2-4.2-2-6.5-2H3v14h2.5c2.3 0 4.7.8 6.5 2" />
      <path d="M12 6c1.8-1.2 4.2-2 6.5-2H21v14h-2.5c-2.3 0-4.7.8-6.5 2" />
      <line x1="12" y1="6" x2="12" y2="20" />
    </Svg>
  );
}

/** Plus = the Add New toolbar action (FRG-UI-003). */
export function PlusIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </Svg>
  );
}

/** Import = the library-import toolbar action (FRG-UI-003). */
export function ImportIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 3v12" />
      <path d="M8 11l4 4 4-4" />
      <path d="M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2" />
    </Svg>
  );
}

export function RefreshIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M21 12a9 9 0 1 1-2.64-6.36" />
      <path d="M21 3v6h-6" />
    </Svg>
  );
}

export function FolderScanIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M3 7V5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      <path d="M8 13h8" />
    </Svg>
  );
}

export function SearchIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="11" cy="11" r="7" />
      <line x1="21" y1="21" x2="16.5" y2="16.5" />
    </Svg>
  );
}

/** Person icon = interactive search (Sonarr's idiom). */
export function PersonIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4 3.6-6 8-6s8 2 8 6" />
    </Svg>
  );
}

export function WrenchIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M14.7 6.3a4.5 4.5 0 0 0-6 6L3 18l3 3 5.7-5.7a4.5 4.5 0 0 0 6-6L14 13l-3-3z" />
    </Svg>
  );
}

export function TrashIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 7h16" />
      <path d="M9 7V4h6v3" />
      <path d="M6 7l1 14h10l1-14" />
    </Svg>
  );
}

export function CloseIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <line x1="5" y1="5" x2="19" y2="19" />
      <line x1="19" y1="5" x2="5" y2="19" />
    </Svg>
  );
}

/** Overflow ("more actions") trigger — three filled dots, horizontal. */
export function MoreIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="5" cy="12" r="1.6" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none" />
      <circle cx="19" cy="12" r="1.6" fill="currentColor" stroke="none" />
    </Svg>
  );
}

export function SpinnerIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M21 12a9 9 0 1 1-9-9" />
    </Svg>
  );
}
