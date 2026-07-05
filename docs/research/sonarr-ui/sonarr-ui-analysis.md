# Sonarr v4 UI Analysis — screenshot-grounded research for foragerr change 7

Source rig: Sonarr v4.0.19.2979 (lscr.io/linuxserver/sonarr:latest) in Docker
(`sonarr-research`, port 8989), dark theme, 1440x900 viewport (plus 900px responsive
set), library seeded with 8 real series (TheTVDB metadata + posters), SABnzbd and
Newznab behaviour simulated by local stub servers so Activity/Queue, History and
Interactive Search render with real data.

All anatomy below is described from the captured PNGs in this directory, not from
memory. Token values are cited from the Sonarr frontend source in
`/Users/adrian/Projects/foragerr/.reference/sonarr/frontend/src/Styles/`.

---

## 1. Shared layout skeleton (every screen)

Three fixed chrome regions + scrolling content:

| Region | Size (at 1440px) | Contents |
|---|---|---|
| Top header | full width x 60px (`headerHeight`) | app logo (left, 60px square), global search input (underline style, aligned with content), donate heart + user icon (right) |
| Left sidebar | 210px (`sidebarWidth`) x full height | icon + label nav: Series, Calendar, Activity, Wanted, Settings, System. Active item gets lighter bg (#333) + accent-colored label + 3px left highlight bar. Child items (Add New, Queue, Missing, settings sections...) indent under the active parent and are always expanded while in that section. Numeric badges (queue count = amber, health issues = red) right-align in the row |
| Page toolbar | content width x 60px (`toolbarHeight`) | two groups: action buttons left (icon over 2-line label, ~60px wide each, thin separators between logical groups), view controls right (Options / View / Sort / Filter dropdown-menu buttons) |
| Content | remainder, `20px` padding (`pageContentBodyPadding`) | page-specific |
| Right jump bar | ~24px strip, series index only | alphabet letters, click = scroll |

Modals overlay everything except nothing — they sit above header and sidebar
(`modalBackdropBackgroundColor` rgba(0,0,0,.6), content #2a2a2a, `modalBodyPadding`
30px). Modal shell = title bar (larger text, close X right) / scrolling body / footer
bar with buttons (destructive left, confirm cluster right).

Shared primitive list used in the per-screen inventories below:

- **P1 sidebar nav item** (icon, label, badge, active state, child indent)
- **P2 page toolbar button** (icon over small label; disabled = dimmed; toggled = accent icon)
- **P3 toolbar menu button** (label + caret, opens dropdown menu: View/Sort/Filter/Options)
- **P4 data table** (uppercase-ish bold header row, 1px separator rows, hover bg
  rgba(255,255,255,.08), gear icon in header right for column config)
- **P5 poster card** (2:3 image, corner status triangle, text footer block, progress bar)
- **P6 modal shell** (title/body/footer as above)
- **P7 form row** (right-aligned label column 150-250px — `formLabelSmallWidth`/`formLabelLargeWidth`,
  input column max ~500px, help text under input, warning-orange label when advanced)
- **P8 labeled chip/tag** (small rounded rect, colored bg: quality gray, status
  green/red/amber, category kinds)
- **P9 progress bar** (5/15/20px heights per `progressBarSmallHeight/Medium/Large`; blue
  fill; purple = downloading in episode rows)
- **P10 icon button** (bare icon, hover lightens; used in table row actions)
- **P11 card** (settings item card: #333 bg, name + status chips, entire card clickable
  — implemented as an invisible `button.Card-underlay` beneath a content overlay; a
  separate `+` card adds new)
- **P12 enhanced select** (button-styled select with caret; options render in popper)
- **P13 check input** (square checkbox, accent blue when checked, help text to right)
- **P14 page jump bar** (alphabet strip)
- **P15 legend / stats footer** (color swatch + meaning list, label:value stat columns)
- **P16 alert/callout** (full-width rounded box, tinted bg + colored border: info blue,
  warning yellow-olive, danger red)

---

## 2. Per-screen analysis

### 01-library-posters.png — Series index, poster view
- **Anatomy**: chrome + content grid of poster cards, 7 per row at 1440 (≈170px posters,
  `seriesIndexColumnPadding` 10px gutters); alphabet jump bar right; footer legend +
  library stats (P15) after the grid.
- **Components**: P1, P2 (Update All, RSS Sync, Select Series, Test Parsing), P3
  (Options/View/Sort/Filter), P5 poster cards, P14, P15.
- **Poster card detail**: corner triangle top-right encodes status (red = missing
  episodes/monitored, blue = continuing complete, green = ended complete, purple bar =
  downloading); footer block shows "Monitored" + quality profile name; hover reveals
  action icons (refresh/edit seen in DOM: `Refresh Series`, `Edit Series` buttons per card).
- **Interactions**: card click → series detail; title bar hover tooltip; select mode via
  toolbar turns cards checkable; legend explains the color coding.
- **foragerr mapping**: FRG-UI-003 (library index). Comic divergence: poster = volume
  cover (CV image), footer shows publisher + monitored; corner triangle semantics map to
  "missing issues" / "complete" / "downloading". The alphabet jump bar is worth keeping
  for big comic libraries.

### 02-library-table.png — Series index, table view
- **Anatomy**: same chrome; content becomes full-width P4 table: bookmark(monitor) +
  status icons, Series Title (link, sorted asc marker), Network, Quality Profile, Next
  Airing, Seasons count, Episodes progress pill ("0+1/63" = files+queued/total, gray
  fill ratio), row action icons (refresh, wrench=edit); gear header icon = column
  chooser. Same legend/stats footer as poster view.
- **Interactions**: view switched via View menu (P3) — options Table/Posters/Overview;
  header click sorts; row hover highlights; per-row quick actions at right.
- **foragerr mapping**: FRG-UI-003 table mode. Columns become: Title, Publisher,
  Profile, Next Expected Issue, Volumes?, Issues progress pill. The "0+1/63" pill
  (have+queued/total) is a compact idiom worth copying exactly.

### 03-series-detail.png / 03b-series-detail-expanded.png — Series detail
- **Anatomy**: toolbar (Refresh & Scan, Search Monitored | Preview Rename, Manage
  Episodes, History | Series Monitoring, Edit, Delete || Expand All right); hero band
  (~420px tall) = blurred fanart bg + dark overlay, poster left (~250px), title block
  right: bookmark monitor toggle + huge title (~48px), meta line (runtime, heart
  rating, genre, years), chip row (path, size on disk, profile, monitored, status,
  language, network — each an icon+text chip P8), Links chip, then overview paragraph;
  prev/next series arrows top right of hero. Below: season accordion cards (#424242
  header `seasonBackgroundColor`), one per season, newest first.
- **Season header**: monitor bookmark, "Season 2" title, count pill ("0+1/10", purple
  when downloading), expand chevron center, right icon cluster: search (auto), person
  (interactive search), org-chart (episode file org?), file, history.
- **Expanded (03b)**: inner P4 episode table: monitor bookmark, #, Title (+ "Season
  Finale" blue chip), Air Date, Status (warning icon = missing, or purple P9 progress
  bar when downloading — visible on 2x05), row actions: auto-search icon + person
  (interactive search per episode).
- **Interactions**: season header click or chevron expands; every episode row has
  its own search entry points; episode title click opens episode modal
  (Details/History/Search tabs).
- **foragerr mapping**: FRG-UI-004 (volume/series detail). Comic divergence: seasons →
  volumes is NOT 1:1 — comics are usually one volume = one series entity in CV, so
  foragerr detail is more often a single flat issue table; keep the accordion only if
  grouping annuals/specials/TPBs. The hero band (cover + chips + description) ports
  directly. Per-issue search icons port directly (FRG-UI-007 entry point).

### 04-add-new-series.png — Add new series
- **Anatomy**: no toolbar; content = large search input (magnifier prefix box + clear
  X suffix, accent focus ring, placeholder "eg. Breaking Bad, tvdb:####"), then result
  cards stacked vertically: poster left (~170px), right block = Title (Year) + external
  link icon, chip row (rating heart %, language, network, genre, season count, Ended
  chip red), overview text, "Metadata is provided by TheTVDB" footnote.
- **Interactions**: type-ahead search (debounced, hits metadata API); card click expands
  inline add form (root folder, monitor scheme, quality profile, season folder, start
  search checkboxes + Add button) — not captured but form fields follow P7/P12.
  The global header search box separately offers "Existing Series / Add New Series"
  jump menu.
- **foragerr mapping**: FRG-UI-005 (add series/volume via ComicVine search). Direct
  port: search box + result cards with CV covers, publisher/year/issue-count chips,
  deck text. "tvdb:####" ID-search idiom → "cv:4050-XXXX" idiom.

### 05-activity-queue.png — Activity: Queue
- **Anatomy**: toolbar (Refresh | Grab Selected, Remove Selected; right Options/Filter);
  P4 table: select checkbox column, status icon (download arrow, cloud variants =
  pending/delay, pause), Series link, Episode "5x14", Episode Title, Quality chip,
  Formats, Time Left, Progress (P9 blue bar w/ % on hover), row-end icons (person =
  manual import needed, X = remove). Pagination strip bottom center (first/prev "1/1"
  next/last), "Total records: 6" right.
- **Row states captured**: Downloading (partial bar + timeleft), Paused (pause icon,
  dash timeleft), Queued (cloud icon, 00:00:00), Completed-importPending (full bar +
  person icon = "waiting to import" affordance), Failed (red cloud icon, full bar).
- **Interactions**: checkbox multi-select drives toolbar bulk actions; X removes with
  confirm modal; person icon opens manual import; status icons have tooltips.
- **foragerr mapping**: FRG-UI-006 (queue). Ports almost verbatim for SAB + DDL
  downloads; Episode column becomes Issue ("Saga #61"); one extra source column may be
  needed to distinguish SABnzbd vs built-in DDL client.

### 06-interactive-search.png — Interactive search modal
- **Anatomy**: P6 modal, wide (~90% viewport, `modalBodyPadding` 30px). Title
  "Interactive Search - Season 2". Body = filter button top-right + full-width P4
  release table: Source (nzb chip, blue), Age, Title (accent link color), indexer
  flag icon, Indexer name, Size, Peers (empty for usenet), Languages chip, Quality
  chip, profile-score column, flags, rejection column (red ! icon with tooltip),
  download icon + person-with-+ icon (grab + grab-override) per row. Footer: Close.
- **Interactions**: column headers sort (default sort by score/quality desc — 2160p
  rejected rows sank when profile max is 1080p in earlier probe: rejections show the
  red !); download icon grabs immediately; hover on ! shows rejection reasons; filter
  menu narrows releases. NOTE: season-level search defaults to a **Season Pack
  filter** — single-episode releases are hidden ("All results are hidden by the
  applied filter" callout observed before the stub returned S02 pack names).
- **foragerr mapping**: FRG-UI-007 (interactive search). Ports directly at issue level.
  Comic divergence: no season-pack concept per se, but "volume pack / trade" releases
  could reuse the pack-filter idea; rejection tooltips (wrong size, older version,
  quality cutoff) map to foragerr's decision engine output.

### 07-settings-indexers.png — Settings: Indexers
- **Anatomy**: settings pages swap the sidebar children to section list (Media
  Management ... UI). Toolbar: Show Advanced (toggle w/ red x/green check badge), No
  Changes (disabled save), Test All Indexers, Manage Indexers. Content: "Indexers"
  section heading (underlined full-width rule), P11 card grid (indexer card: name,
  copy icon on hover, green chips RSS/Automatic Search/Interactive Search; `+` card),
  then "Options" heading with P7 form rows (Minimum Age/Retention/Maximum Size, each
  input has trailing unit label inside the field: minutes/days/MB).
- **Interactions**: card click opens edit modal; + opens add-picker modal (list of
  indexer implementations); Show Advanced toggles orange-labelled advanced rows
  globally across settings; save button lights when dirty ("No Changes" ↔ "Save
  Changes").
- **foragerr mapping**: FRG-UI-008 (indexer settings: DogNZB, NZB.su). Structure ports
  1:1 including the capability chips (RSS/Auto/Interactive).

### 08-edit-indexer-modal.png — Edit indexer modal (schema-driven form)
- **Anatomy**: P6 modal, ~720px wide, title "Edit Indexer - Newznab". Body = P7 form
  rows generated from the backend field schema: Name (text), Enable RSS / Enable
  Automatic Search / Enable Interactive Search (P13 checkboxes each with help text
  right of the box), URL (text), API Key (password-masked), Categories (multi-select
  P12 showing selected values as chips TV/HD/UHD inside the control), Anime
  Categories (empty variant), Anime Standard Format Search (checkbox), Tags (tag
  input). Footer: Delete (danger, left) | advanced-settings gear indicator | Test,
  Cancel, Save (primary blue) right.
- **Interactions**: every field's help text comes from the schema `helpText`; Test
  runs live validation and paints field-level errors; Save disabled until valid.
  This is THE pattern to copy: the backend `/api/v3/indexer/schema` returns typed
  field definitions (`textbox`, `checkbox`, `select`, `tag`) and the UI renders them
  generically.
- **foragerr mapping**: FRG-UI-008. foragerr's provider settings (Newznab indexers,
  SABnzbd, DDL sources) should adopt the same schema-driven contract so new
  providers need zero frontend work.

### 09a/09b — Settings: Download Clients + edit modal
- **09a anatomy**: same skeleton as 07: card grid (SABnzbd card w/ green "Enabled"
  chip, + card), then "Remote Path Mappings" section: P16 info callout + empty table
  (Host/Remote Path/Local Path headers) with + add row icon right.
- **09b anatomy**: P6 modal "Edit Download Client - SABnzbd": Name, Enable checkbox,
  Host, Port, Use SSL checkbox, API Key (masked), Username, Password, Category
  (w/ "category avoids conflicts" help), Recent Priority (P12 select "Default") —
  cut below: Older Priority, tags, advanced. Footer identical to 08 (Delete | gear |
  Test/Cancel/Save).
- **foragerr mapping**: FRG-UI-009 (download clients: SABnzbd + built-in DDL). Direct
  port including Test button semantics (calls stub `mode=version`+`get_config` etc.).
  Remote path mappings likely still needed (Docker path translation).

### 10-media-management.png — Settings: Media Management (Show Advanced ON)
- **Anatomy**: long P7 form page, section headings: Episode Naming, Folders (more below
  fold: Importing, File Management, Permissions, Root Folders). Naming section: Rename
  Episodes checkbox, Replace Illegal Characters, Colon Replacement (select "Smart
  Replace"), Series Folder Format / Season Folder Format / Specials Folder Format —
  monospace text inputs with a blue `?` suffix button (opens token-reference popover)
  and live "Example: The Series Title's!" preview under each; Multi Episode Style
  select. **Advanced rows have orange labels** (`advancedFormLabelColor` #ff902b) —
  visible: Series Folder Format, Specials Folder Format, Create Empty Series Folders,
  Delete Empty Folders. Toolbar shows "Hide Advanced" toggled + "No Changes".
- **Interactions**: `?` opens naming-token cheatsheet; examples recompute as you type;
  save-bar model (toolbar button) instead of per-form submit.
- **foragerr mapping**: FRG-UI-012 (M2, media management / naming). Naming tokens
  become {Series Title}/{Volume}/{Issue:000}; the live example preview + token
  popover is the key UX to replicate for comic renaming (FRG-IMP naming reqs).

### 11-wanted-missing.png — Wanted: Missing
- **Anatomy**: toolbar (Search All | Unmonitor Selected | Manual Import; right
  Options/Filter); P4 table: checkbox, Series Title link, Episode 5x08, Episode
  Title, Air Date (sorted desc), Status (warning icon; one row shows purple progress
  bar = currently downloading), row actions: auto search + interactive search icons.
  Paged (below fold).
- **foragerr mapping**: FRG-UI-011 (M2, wanted/missing issues). Direct port with
  Issue column; "Air Date" → "Store/Cover Date".

### 12-activity-history.png — Activity: History
- **Anatomy**: toolbar (Refresh; Options/Filter right); P4 table: event icon column
  (cloud-down = grabbed), Series link, Episode 2x03, Episode Title, Quality chip,
  Formats, Date (sorted desc), info (i) icon opening event-details modal. Pagination +
  total. (Empty-state variant also observed: P16 callout "No history found".)
- **foragerr mapping**: FRG-UI-010 (M2, history). Event types map: grabbed /
  imported / failed / deleted / renamed → same iconography.

### 13-system-status.png — System: Status
- **Anatomy**: System sidebar children (Status, Tasks, Backup, Updates, Events, Log
  Files). Content sections with underlined headings: Health (P4 table of health-check
  warnings, each row: severity icon, message, wiki-book action icon; plus P16 info
  callout below), Disk Space (table w/ free/total + small P9 bars), About
  (definition list: Version, Package Version, .NET, Docker, Database Sqlite 3.51.2,
  Migration 217, AppData/Startup dirs, Mode, Uptime), More Info (links). Health item
  count = red badge on System nav + Status child.
- **foragerr mapping**: FRG-UI-016 (M2, system status). Health-check pattern (rule id,
  message, wiki link) is worth adopting early — it surfaced our stub's path problem
  ("SABnzbd places downloads in /downloads/complete/tv but this directory does not
  appear to exist inside the container") unprompted.

### 14-system-tasks.png — System: Tasks
- **Anatomy**: two sections: Scheduled (P4 table: Name, Interval, Last Execution
  (relative), Last Duration, Next Execution, trigger-now icon per row) and Queue
  (recent command runs: type icon + green check, Name, Queued/Started/Ended relative
  times, Duration).
- **foragerr mapping**: FRG-UI-016. foragerr's scheduler (RSS sync, refresh, health)
  should expose the same two views; the "run now" per-row icon is cheap and useful.

### Responsive set (r01/r02/r03 @ 900px)
- Sidebar **remains expanded** at 900px (collapse breakpoint is `breakpointSmall`
  768px — below that it becomes a hamburger overlay; 900 > 768 so still docked).
- r01: poster grid reflows 7 → 4 columns; footer stats stack under legend instead of
  side-by-side; toolbar buttons keep labels.
- r02: series detail hero: poster image dropped entirely (title block takes full
  width), chips wrap to two rows, overview clamps; season cards full width, right
  icon cluster intact.
- r03: queue table drops columns progressively (Progress squeezed, Formats retained
  but Time Left wraps); long titles wrap to 2-3 lines growing row height; pagination
  intact. Column priority appears hard-coded per table (Sonarr hides via CSS at
  breakpoints).

---

## 3. Design tokens (from `.reference/sonarr/frontend/src/Styles/`)

### Dark theme palette — `Themes/dark.js`
| Token | Value | Note |
|---|---|---|
| `pageBackground` | `#202020` | app/content bg |
| `pageHeaderBackgroundColor` | `#2a2a2a` | top header |
| `sidebarBackgroundColor` | `#2a2a2a` | sidebar |
| `sidebarActiveBackgroundColor` | `#333333` | active nav item |
| `toolbarBackgroundColor` | `#262626` | page toolbar |
| `cardBackgroundColor` | `#333333` | cards (settings, season) |
| `modalBackgroundColor` | `#2a2a2a` | + backdrop rgba(0,0,0,.6) |
| `inputBackgroundColor` | `#333` | inputs (readonly `#222`) |
| `textColor` / `defaultColor` | `#ccc` | body text |
| `disabledColor` | `#999`; `dimColor` `#555` | |
| `helpTextColor` | `#909293` | form help |
| `sonarrBlue` / `themeBlue` | `#35c5f4` | brand accent (nav active, toolbar hover/selected) |
| `primaryColor` / `linkColor` | `#5d9cec` | buttons, links (hover `#1b72e2`) |
| `successColor` | `#00853d` (button bg `#27c24c`) | |
| `dangerColor` | `#f05050` | |
| `warningColor` | `#ffa500` (button bg `#ff902b`) | |
| `selectedColor` | `#f9be03` | |
| `advancedFormLabelColor` | `#ff902b` | orange advanced labels |
| `borderColor` | `#858585`; input border `#dde6e9` | |
| `tableRowHoverBackgroundColor` | `rgba(255,255,255,0.08)` | |
| `seasonBackgroundColor` | `#424242`; `episodesBackgroundColor` `#2a2a2a` | |
| `usenetColor` | `#17b1d9`; `torrentColor` `#00853d` | protocol chips |
| `queueTrendColor` (progress bg) | `#727070` (`progressBarBackgroundColor`) | |
| `popoverTitleBackgroundColor` | `#424242`; body `#2a2a2a` | |
| `inputFocusBorderColor` | `#66afe9` + rgba(102,175,233,.6) glow | |

Light theme counterpoints (`Themes/light.js`): `pageBackground #f5f7fa`, text
`#515253`, sidebar stays dark (`#3a3f51`) — Sonarr's light mode keeps a dark sidebar.
Theme switching: `Themes/index.js` — `auto` resolves via `prefers-color-scheme`.

### Dimensions — `Variables/dimensions.js`
- `headerHeight` 60px, `toolbarHeight` 60px, `toolbarButtonWidth` 60px
- `sidebarWidth` **210px**
- `pageContentBodyPadding` 20px (10px small screens)
- breakpoints: XS 480 / S 768 / M 992 / L 1200 / XL 1450 (px)
- form: group widths 550/650/800/1200; label widths 150 (small) / 250 (large); label
  right margin 20px
- `modalBodyPadding` 30px
- progress bars 5/15/20px; `jumpBarItemHeight` 25px; `qualityProfileItemHeight` 30px
- `seriesIndexColumnPadding` 10px (5px small); overview info row 21px

Table row heights are not tokenized — they derive from cell padding (~8px vertical
on 14px text ≈ 37-38px rows as measured in the queue capture).

### Fonts — `Variables/fonts.js`
- `defaultFontFamily`: `Roboto, "open sans", "Helvetica Neue", Helvetica, Arial, sans-serif`
- `monoSpaceFontFamily`: `"Ubuntu Mono", Menlo, Monaco, Consolas, "Courier New", monospace`
  (used in naming-format inputs)
- sizes: 11 / 12 / **14 (default)** / 15 / 16 px; `lineHeight` 1.528571429

### z-index — `Variables/zIndexes.js`
`pageJumpBar` 10, `modal` 1000, `popper` 2000.

---

## 4. Surprises / design-discussion items for foragerr

1. **Forced-auth nag modal**: Sonarr v4 blocks the whole UI with an "Authentication
   Required" modal until an auth method is chosen (`AuthenticationMethod None` is no
   longer a legal steady state; `External` + `DisabledForLocalAddresses` silences it).
   For foragerr on Tailscale, decide the auth story up front so we never need such a
   modal.
2. **Schema-driven provider forms** (08/09b) are the highest-leverage pattern: the
   backend ships field definitions + help text + validation, the frontend has ONE
   generic form renderer. Sonarr's Test button behaviour (live round-trip with
   field-level errors) belongs in FRG-UI-008/009 acceptance criteria.
3. **Season-pack default filter** in season-level interactive search silently hides
   results ("All results are hidden by the applied filter" is the only clue). If
   foragerr has volume-level search, don't repeat this quiet-filter trap — show the
   active filter inline.
4. **Save model inconsistency is a feature**: settings pages use a toolbar
   "Save Changes" (page-dirty model), while modals use footer Save. Users seem
   trained on it; copying it avoids invented complexity.
5. **The "0+1/63" progress pill** (have + queued / total) compresses three facts into
   one glanceable element — strong candidate for foragerr's library table and volume
   headers.
6. **Health checks with wiki links** (13) caught our stub's fake path immediately.
   A comic-domain health system (unreachable SAB, dead indexer, unwritable library
   path, CV rate-limit) is cheap and high-value.
7. **Light theme keeps the dark sidebar** — a Sonarr signature. If foragerr follows
   the "Sonarr-shaped, ant accent" memory note, this is the look to preserve.
8. **Poster corner-triangle status** is subtle (easy to miss, colorblind-hostile —
   Sonarr ships explicit colorImpaired gradient tokens as mitigation). Consider a
   clearer affordance for missing-issues state.
9. **Sidebar stays docked until 768px** — tablets landscape get the full app. The
   900px captures show tables handle narrowness by column-dropping, not horizontal
   scroll.

## 5. FRG-UI requirement → capture index

| Requirement | Capture(s) |
|---|---|
| FRG-UI-003 library index | 01, 02, r01 |
| FRG-UI-004 series/volume detail | 03, 03b, r02 |
| FRG-UI-005 add new | 04 |
| FRG-UI-006 queue | 05, r03 |
| FRG-UI-007 interactive search | 06 |
| FRG-UI-008 indexer settings | 07, 08 |
| FRG-UI-009 download clients | 09a, 09b |
| FRG-UI-010 history (M2) | 12 |
| FRG-UI-011 wanted/missing (M2) | 11 |
| FRG-UI-012 media management (M2) | 10 |
| FRG-UI-016 system status/tasks (M2) | 13, 14 |
