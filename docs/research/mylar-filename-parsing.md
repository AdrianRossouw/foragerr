# Mylar3 Comic Filename Parsing — Behavioral Mining Report

Source studied: `.reference/mylar3` (all paths below relative to that clone).
Core parser: `mylar/filechecker.py` (class `FileChecker`, entry `parseit()` at
filechecker.py:230). Supporting logic: `mylar/helpers.py` (`issuedigits`,
`decimal_issue`, `rename_param`), `mylar/__init__.py:179-206` (`ISSUE_EXCEPTIONS`),
`mylar/search_filer.py` (volume interpretation of search results),
`mylar/PostProcessor.py:2790-2870` and `mylar/filers.py:490-560` (issue re-formatting
for renames), `mylar/cv.py:786-827,991-992` (booktype from ComicVine metadata).

Mylar3 ships **no unit tests for the parser** (`mylar/test.py` is an rtorrent client;
no filename fixtures anywhere in the repo). Every "expected result" below is derived
from reading the code, its dated inline comments (the author annotates bug fixes with
dates, e.g. `#2019-12-24`, `#2024-01-07`), and from re-executing the tokenizer regexes
in isolation. Uncertain entries are flagged.

---

## 1. Parser architecture (context for the catalogue)

`parseit()` is a single ~1,150-line stateful pass, not a grammar:

1. Extension split & filetype detection (filechecker.py:259-265).
2. Optional story-arc reading-order prefix strip (":273-283).
3. Bracket spacing normalization (":285-306) — inserts a spacer before `(...)` groups
   glued to the previous word.
4. Scan-group ("ripper") tag extraction and removal (":308-344).
5. Embedded issue-ID extraction `[__<id>__]` (":346-354).
6. Non-ASCII segments replaced by sentinel `XCV`; `+ & ' @` replaced by sentinels
   `c11 f11 g11 h11` so regexes don't eat them (":361-399).
7. Tokenization: split on `,`, whitespace, `_` (falling back to also splitting on `.`
   if the result is a single token, i.e. NZB-style dot-separated names), then a master
   regex keeps parenthesized groups, `[...]` groups, decimals, `NNNN-NN-NN` dates,
   ordinals, `N COVERS`, `N PAGE` as single tokens (":374-404).
8. Token-stream reassembly passes: `(of N)` mini-series counts, `36p ctc` page tags,
   `px` merge (":406-457).
9. One big `for sf in split_file:` loop collecting **candidates** with positions:
   `datecheck[]` (years/dates), `possible_issuenumbers[]`, `volume_found{}`,
   plus `booktype` flips (":486-864).
10. Arbitration: choose year (rightmost valid, non-future), choose issue number
    (position heuristics + hyphen heuristics + `(of N)` override), choose volume,
    compute `highest_series_pos` = boundary where the series title ends
    (":867-1234).
11. Series title = tokens left of the boundary; sentinel restoration; annual/special
    rewriting; `alt_series`/`alt_issue` guesses; result dict.

Output dict (justparse mode, filechecker.py:1353-1370): `parse_status`
(`success`/`failure`), `type` (extension), `sub` (subdirectory relative to scan root),
`comicfilename`, `comiclocation`, `series_name`, `series_name_decoded` (NFKD),
`issueid`, `alt_series`, `alt_issue`, `dynamic_name`, `series_volume`, `issue_year`,
`issue_number`, `scangroup`, `booktype`, `reading_order`.

---

## 2. Behavioral catalogue

### 2.1 File formats / extensions

- Recognized comic extensions: `.cbr`, `.cbz`, `.cb7`, `.pdf` — hardcoded twice
  (filechecker.py:260 in `parseit`, :1625 in `traverse_directories`). Entries present
  in config `IGNORE_SEARCH_WORDS` are removed from the tuple (":261).
- `parseit` checks `os.path.splitext(filename)[1].endswith(comic_ext)` **without
  lowercasing** (":262) → `.CBZ` yields `filetype = 'unknown'`; the directory walker
  *does* lowercase (":1660), so uppercase-extension files are enumerated but then have
  their extension mis-stripped. Output `type` = extension sans dot, or `unknown`.
- The extension is removed with `re.sub(filetype, '', filename)` (":270) — the dot is
  an "any char" regex and substitution is global, so a name containing e.g. `acbr`
  anywhere gets mangled.
- Directory walk skips: AppleDouble dirs (":1644-1646), `._` resource forks (":1648),
  zero-byte files (":1669-1671), dotfiles unless the watched series itself starts with
  `.` (":149-155). No .cbt/.cba/.epub support.

### 2.2 Issue numbers — plain forms

- **Pure digits**: any all-digit token is a candidate, *except* at token position 0
  (protects "100 Bullets", "52") (filechecker.py:762-768).
- **`#`-prefixed**: any token containing `#` is assumed to be the issue; the number is
  cut from the raw string between `#` and the next space/underscore/dot, trailing `)`
  trimmed; `#` stripped from final output (":671-692, :1016-1017).
- **Decimals**: tokens parsing as `float > 0` are decimal issue candidates ("15.5",
  ".5") (":776-800). Also a two-token repair: digits followed by digits with a literal
  `.` between them in the raw filename are re-joined ("[DECiMAL-DETECTION]",
  ":628-654).
- **Negative issues**: `float(sf) < 0` → candidate kept with sign ("-1")
  (":779-787). helpers.issuedigits scores it `int(x)*1000 - 1` (helpers.py:1152-1154).
- **Two adjacent numbers**: "2 seperate numbers detected. Assuming 2nd number is the
  actual issue" (":603-627) — e.g. `Series 2 015` picks 015.
- **Number ranges** (`1-2`, `112/113`, `2 & 3`): not handled by filechecker; only by
  `helpers.issuedigits` for ordering, scored as first + 0.5 (helpers.py:1206-1228),
  with several hardcoded literals (`'9-5'`, `'2 & 3'`, `'4 & 5'`, `'112/113'`,
  `'14-16'`, `'380/381'`).
- **Issue selection**, when multiple candidates (":956-1014): iterate candidates by
  position, right-most first; a number that is the *final* text after a hyphen wins
  ("Numeric detected as the last digit after a hyphen", :970-979); a candidate flagged
  by `(of N)` wins outright (`validcountchk`, :981-986); candidates at the year
  position are skipped (":996-1002); otherwise the right-most survivor is chosen.
  Numbers positioned inside an issue title after a dash are demoted to `dash_numbers`
  and only used if nothing else matched (":987-994, :1019-1032).

### 2.3 Issue numbers — alphanumeric suffixes & named issues

- Master exception list `ISSUE_EXCEPTIONS` (mylar/__init__.py:179-206): `DEATHS,
  ALPHA, OMEGA, BLACK, DARK, LIGHT, AU, AI, INH, NOW, BEY, MU, HU, LR, A, B, C, X, O,
  WHITE, SUMMER, SPRING, FALL, WINTER, PREVIEW, DIRECTOR'S CUT, (DC)`.
- Trigger in filechecker (":507-560): strip digits from token; if the remainder equals
  an exception (case-insensitive):
  - previous token was a number → combine: `15 AU` → issue `15 AU` (":524-542);
  - glued form `15A` → alpha stripped, digit remainder validated → issue `15A`
    (":544-553);
  - pure-alpha token (e.g. `Alpha`) only accepted if preceded by `#` in the raw name
    (":554-560).
- `Director's Cut` gets bespoke two-token matching (`Director's` + `Cut`,
  apostrophe-sentinel-aware) (":507-517).
- Dotted forms (`18.NOW`, `24.INH`, `1.MU`) survive because the tokenizer keeps
  `#?\d\.\d+` and the decimal-repair pass rejoins digit+`.`+suffix; ordering/rename
  code recognizes them explicitly (PostProcessor.py:2790-2812 maps to canonical
  `.NOW`, `.INH`, `.BEY`, `.MU`, `.HU`, `.DEATHS`, ` AU`, ` AI`).
- `NOW!` → `!` stripped (helpers.py:441-443, :1022-1023).
- Ordering integers: `issuedigits` = `int * 1000` for plain numbers; alpha suffixes add
  `ord()` sums of the letters (helpers.py:998-1069); pure words (`ALPHA`, `OMEGA`,
  seasons) become bare `ord()` sums (":1194-1201); unparseable → sentinel
  `999999999999999`.

### 2.4 Issue numbers — unicode fractions & infinity

- `½ ¼ ¾ ∞` (and `â` as a mis-encoding artifact) map to `.5/.25/.75/9999999999`
  (helpers.py:417, :1091-1093; PostProcessor.py:2813-2820 maps `½`→`0.5` etc.).
- In filechecker itself, non-ASCII runs become `XCV` tokens; an `XCV` token is a
  first-class issue candidate ("[SPECIAL-CHARACTER ISSUE]", filechecker.py:562-571),
  and `000.0000½`-style composites are re-joined (":804-824). The original glyphs are
  restored into `issue_number` at the end (":1236-1241).
- The literal word `infinity` parses as `float('inf')`: if it sits within the first 3
  tokens it is treated as series title ("Infinity Gauntlet"), otherwise it becomes a
  (nonsense) decimal issue candidate (":788-800). `(of infinity)` is explicitly
  excluded from mini-series counts (":423-424).

### 2.5 Mini-series counts, covers, page tags

- `(of 12)` / `01 of 7` / `01 (of 7.3)` (decimal totals supported): the number
  *preceding* the count is flagged as the true issue (`validcountchk`)
  (filechecker.py:406-433, :576-595, :981-986).
- `N covers` tokens are consumed and dropped (":597-601); with config
  `IGNORE_COVERS`, search results whose title contains `coversonly`/`coveronly`
  are rejected outright (search_filer.py:197-202).
- Page-count scanner tags `36p ctc`, `NNNNpx` are merged/dropped so they can't be
  mistaken for issues (":436-449, comment :406-408).

### 2.6 Volume designators

Detection loop at filechecker.py:695-757; trigger words: token starts with `v`, or
contains `vol` / `volume` / `part`, excluding the spelled numbers `one..six`:

- `v2`, `V2013`, `vol4`, `v10` — token has digits after prefix → volume = digits only
  (":696-700). Output is always re-prefixed: `series_volume = 'v' + digits`
  (":1066) — so `Vol. 04` → `v04` (leading zeros preserved).
- `vol` / `vol.` alone → `volumeprior` state; the *next* numeric token is consumed as
  the volume and the tokens are merged (`sep_volume=True`) (":727-732, :701-719).
- `volume` with digits glued (`volume2`) → digits; `volume` alone → wait for next
  token (":733-741).
- `part` (exact word) is treated as a volume label too, unless the watched series
  title itself contains "part" (":742-751) — `Part 2` ⇒ `v2`.
- Roman numerals after a volume word (`Vol III`) are **discarded** — recognized only
  to reset state, never captured (":753-757).
- A year with a trailing dash (`(1953-)` → token `1953-`) is treated as a
  volume-as-year, not a cover year (":492-500).
- Default volume: if no volume found and booktype is not `issue` (TPB/GN/HC), or no
  issue number was found at all, `series_volume = 'v1'` — except when the name
  contains `2000ad` (":1083-1086).
- Downstream interpretation (search_filer.py:533-580): `v` + 4 digits = "volume is a
  year" (`v2013`); `v` + 1-3 digits = ordinal volume; bare digit volumes length ≤4
  similarly split. Renamer honors `$VolumeY`/`$VolumeN` from this.
- Volume/issue interplay: if extra tokens sit between the volume label and the issue
  number, the volume token is relocated next to the issue (":1067-1081); volume
  *after* issue number is handled by a 2019-10-02 fix (":1072-1074).

### 2.7 Years, cover dates, multiple years

- Candidate detection: token (after removing `(),`) must contain `19` or `20`, be ≥4
  chars, not start with `v19`/`v20`, and must parse via `checkthedate()`
  (filechecker.py:490-504).
- `checkthedate()` accepts formats `%Y`, `%Y-`, `%b %d, %Y`, `%B %d, %Y`, `%B %d %Y`,
  `%m/%d/%Y`, `%m/%d/%y`, `(%m/%d/%Y)`, `%b %Y`, `%B%Y`, `%b %d,%Y`, `%m-%Y`,
  `%B %Y`, `%Y-%m-%d`, `%Y-%m`, `%Y%m`, `%Y-%m-00` and returns just the **year**
  (":1806-1882). Full dates like `2019-05-22` survive tokenization as one token
  (master regex keeps `\d{4}-\d{2}-\d{2}`, ":404).
- Right-most date wins ("if there's more than one date, assume the right-most date is
  the actual issue date", ":491); years **in the future** (> current year + 1) are
  rejected and treated as series-title words — this is what keeps "Spider-Man 2099"
  intact (":874-884).
- Multiple years: a year positioned inside the series-title range is ignored as YEAR
  (":1106-1122); `issue2year` handles the case where the only issue-number candidate
  *is* a year (e.g. `Action Comics 2019 (2019)`) (":907-916).
- `year annual` pairs: regex `(\d{4})(?=[\s]|annual\b|$)` used to spot e.g.
  `1997 Annual` / `2021annual` (":480, :1290, :1435, :1539).

### 2.8 Annuals / specials / biannuals

- In parse-only mode (import/scan): if `annual` remains in the parsed series name, the
  issue number is rewritten to `Annual <n>` (or bare `Annual`, or `<year> annual`) and
  `annual` is removed from the series name; same for `special` → `Special <n>`
  (filechecker.py:1283-1307). Gated on config `ANNUALS_ON` and on the watched title
  not already containing annual/special.
- Fallbacks when no issue number: annual + trailing year in name ⇒ the year *is* the
  issue number ("Possible Annual detected... assuming year (%s) as issue number",
  ":1309-1323).
- In watch-match mode (`matchIT`): `annualisation` — a file with `annual` matching a
  watched series without it (or vice versa) is matched and `justthedigits` becomes
  `Annual <n>` / `<year> Annual` (":1432-1466); `biannual` → `BiAnnual <n>`
  (":1531-1535, :1576-1579); `special` similarly (":1467-1476, :1584-1585). Annuals
  tracked as separate ComicVine series are linked via alternate-search entries tagged
  `!!<comicid>` (":1774-1796).
- `Annual`/`Special` tokens immediately before the issue number are kept *out* of the
  series title trim (":1096-1097).

### 2.9 Booktype (TPB / GN / HC / one-shot / issue)

- Default `booktype = 'issue'` (filechecker.py:473).
- Token `tpb` or `digital tpb` (paren-stripped) ⇒ `TPB`; issue number is then assumed
  to be the **volume** number, defaulting to `1` if none (":829-842).
- Token `gn` / `graphic novel` ⇒ `GN`; `hc` / `hardcover` ⇒ `HC` (":844-849) — note
  the two-word forms can never match because tokens are single words.
- No issue number but a volume present ⇒ `booktype = 'TPB/GN/HC/One-Shot'`
  (":1057-1059, :1311-1317).
- 2024-01-07 one-shot rule: if the "issue number" token is identical to the year token
  (e.g. `Book Title 2023 (2023)`) the number is assumed to be part of the title, issue
  number is dropped, booktype becomes `TPB/GN/HC/One-Shot` (unless `annual` present)
  (":1149-1157).
- Authoritative booktype otherwise comes from ComicVine metadata, not filenames
  (cv.py:786-827; single-issue back-catalog series forced to `One-Shot` at
  cv.py:991-992). Search rejects results whose parsed booktype mismatches the series
  type unless `ignore_booktype` (search_filer.py:506-517); One-Shots are searched as
  issue `1` (search.py:210).

### 2.10 Scan-group / release-group tags

- Hardcoded ripper substrings: `-empire`, `-empire-hd`, `minutemen-`, `-dcp`,
  `Glorith-HD` (filechecker.py:112). A parenthesized group containing one
  (case-insensitive) is extracted as `scangroup` and removed from the working name
  (":308-344) — e.g. `(Minutemen-Faessla)`, `(Son of Ultron-Empire)`,
  `(The Last Kryptonian-DCP)`.
- Glorith-HD gets two bespoke hacks for dot-separated NZB names: comma-date repair
  (":315-331) and "abnormal formatting" issue-number recovery, where the issue is
  taken as the parenthesized token immediately after the year (":938-952).
- Any other group tag (Zone-Empire? actually matches `-empire`; but e.g. `(Oroboros)`)
  is *not* recognized: bracketed tokens simply fall outside the series-title boundary
  and are dropped, or worse, pollute parsing.

### 2.11 Publisher / edition markers

- There is **no** publisher extraction from filenames. Publisher only arrives from the
  watchlist/ComicVine (`Publisher` ctor arg, filechecker.py:66-70).
- Edition/quality markers (`(Digital)`, `(Webrip)`, `digital`) are not modeled; they
  are ignored only by virtue of sitting to the right of the year/issue boundary.
  `digital tpb` is the single explicit edition-aware rule (":829).
- `c2c`/`ctc` ("cover to cover") only recognized in the `36p ctc` page-tag merge.

### 2.12 Directory vs filename cues

- Only the **filename** is parsed; the subdirectory relative to the scan root is
  passed through as `sub` (filechecker.py:232-256) for the caller.
- `match_type` ("folder/file based on how it was matched") is declared twice but never
  populated — always `None` (":1124, :1211, :1590).
- PostProcessor falls back to parsing the *download folder name* when there is no NZB
  name, by pointing a fresh FileChecker at the folder (PostProcessor.py:434-462);
  librarysync parses each file individually (`FileChecker(dir=r, file=comic)`,
  librarysync.py:77).

### 2.13 Unicode & special-character handling

- Watch-title normalization: `?` stripped; em/en/two-em/two-en dashes (`— –
  ⸺ ⸻`) → ` - `; right single quote `’` → ` ' `; NFKD-to-ASCII fold
  (filechecker.py:57-62). Same dash/quote mapping inside `dynamic_replace`
  (":1714-1715).
- Filename side: runs of ≥3 ASCII chars are kept, everything else becomes the `XCV`
  sentinel; the original segments are restored into series name / issue number at the
  end (":361-372, :1236-1247).
- `+ & ' @` are protected as `c11 f11 g11 h11` sentinels and restored (":396-399,
  :1249-1257) — a real filename containing the literal substring `c11` would be
  corrupted.
- `series_name_decoded` = NFKD-normalized series name, kept alongside the raw one for
  matching (":1280).
- `dynamic_name`: punctuation (`/ - : ; ' " , & ? ! + * ( )` and unicode dashes)
  replaced by `|` runs, articles `and`/`the` removed, spaces/underscores/dots
  collapsed — a fuzzy join key used everywhere for series matching (":110-111,
  :1681-1756).

### 2.14 Story-arc reading order

- With `READ2FILENAME` enabled and a story-arc context, a leading `NNN-` (≤3 digits
  before the first hyphen) is stripped and returned as
  `reading_order = {reading_sequence, filename}` (filechecker.py:273-283).

### 2.15 Embedded issue IDs and alternates

- `[__<issueid>__]` anywhere in the name is extracted to `issueid` and removed
  (filechecker.py:346-354) — used to make renamed files self-identifying.
- `alt_series` / `alt_issue`: for `Series - Title 05 (2019)` shapes, the text after
  the first standalone hyphen is remembered as a possible issue title, and the prefix
  as an alternate series name (":1167-1197); when ≥2 words sit between issue # and
  year, they are appended to the series as an alternate (`splitvalue`, ":1145-1166,
  :1265-1277).

### 2.16 Issue formatting on rename (round-trip contract)

- `helpers.rename_param` / filers.py: decimals re-normalized (`.50` → `.5`, `.0`
  dropped) (helpers.py:465-487); zero-padding via `ZERO_LEVEL_N` = `none`/`0x`/`00x`
  (":489-494); alpha exceptions re-attached with their space/dot separator
  (":427-451); negatives prefixed `-` after padding (":506-508); infinity handled
  (":509-511). Annuals rendered as `Annual` in filenames when `ANNUALS_ON`.

---

## 3. Regression corpus (67 filenames)

Legend: expected values are what a **correct** parser should produce; `Mylar:` notes
document where Mylar3's actual behavior differs or is fragile (derived from code
paths cited above). booktype `issue` and empty scangroup omitted for brevity.
`vol` = series_volume, `#` = issue_number, `year` = issue_year.

| # | Filename | series_name | # | vol | year | booktype / notes |
|---|----------|-------------|---|-----|------|------------------|
| 1 | `Batman 404 (1987).cbz` | Batman | 404 | – | 1987 | |
| 2 | `Batman #404 (1987).cbr` | Batman | 404 | – | 1987 | `#` forces issue (fc:671) |
| 3 | `Batman 404.cbz` | Batman | 404 | – | – | no year present |
| 4 | `100 Bullets 050 (2003).cbz` | 100 Bullets | 050 | – | 2003 | leading digits ≠ issue (fc:762) |
| 5 | `52 018 (2006).cbz` | 52 | 018 | – | 2006 | same rule |
| 6 | `2000AD prog 2205 (2020).cbz` | 2000AD prog | 2205 | – | 2020 | Mylar: `2000ad` special-case; 2205 rejected as future year then reused as issue (fc:1047-1056, :1227-1234) |
| 7 | `Spider-Man 2099 001 (1992).cbz` | Spider-Man 2099 | 001 | – | 1992 | 2099 = future year → title (fc:880) |
| 8 | `Batman Beyond 2.0 015 (2013).cbz` | Batman Beyond 2.0 | 015 | – | 2013 | decimal inside title; Mylar likely flags 2.0 as decimal-issue candidate then discards via right-most rule — verify |
| 9 | `X-23 012 (2011).cbz` | X-23 | 012 | – | 2011 | hyphen-digit first word (fc:960-968) |
| 10 | `Amazing Mary Jane (2019) 002.cbr` | Amazing Mary Jane | 002 | – | 2019 | from Mylar comment fc:293 |
| 11 | `Amazing.Spider-Man.798.2018.Digital.Empire.cbr` | Amazing Spider-Man | 798 | – | 2018 | dot-separated NZB name; scangroup Empire only if parenthesized — Mylar: scangroup None here |
| 12 | `Invincible 015.5 (2005).cbz` | Invincible | 015.5 | – | 2005 | decimal issue |
| 13 | `Elephantmen 20.5 (2009).cbz` | Elephantmen | 20.5 | – | 2009 | |
| 14 | `Gold Digger 0.5 (1997).cbr` | Gold Digger | 0.5 | – | 1997 | |
| 15 | `Deadpool -1 (1997).cbz` | Deadpool | -1 | – | 1997 | negative issue (fc:779) |
| 16 | `Uncanny X-Men ½ (1999).cbz` | Uncanny X-Men | ½ (→0.5) | – | 1999 | unicode via XCV (fc:562); helpers maps ½→.5 |
| 17 | `Batman 000.0000½ (2015).cbz` | Batman | 000.0000½ | – | 2015 | composite re-join (fc:804-824, dated comment 10-20-2018) |
| 18 | `Wolverine 027AU (2013).cbz` | Wolverine | 27AU | – | 2013 | glued alpha suffix (fc:544-553) |
| 19 | `Age of Ultron 10 AI (2013).cbz` | Age of Ultron | 10 AI | – | 2013 | adjacent alpha token (fc:524-542) |
| 20 | `Uncanny Avengers 008.NOW (2013).cbz` | Uncanny Avengers | 8.NOW | – | 2013 | dotted suffix |
| 21 | `Mighty Avengers 004.INH (2013).cbz` | Mighty Avengers | 4.INH | – | 2013 | |
| 22 | `Spider-Verse 001.MU (2015).cbz` | Spider-Verse | 1.MU | – | 2015 | |
| 23 | `Avengers 024.NOW! (2014).cbz` | Avengers | 24.NOW | – | 2014 | `!` stripped (helpers:441) |
| 24 | `Amazing Spider-Man 015A (2014).cbz` | Amazing Spider-Man | 15A | – | 2014 | single-letter exception |
| 25 | `Justice League 30 Cover B (2019).cbz` | Justice League | 30 | – | 2019 | desired: `B` is a cover variant, not issue `30 B`; Mylar: risk of `30 B` via exceptions — regression guard |
| 26 | `Fantastic Four 600-X (2012).cbz` | Fantastic Four | 600-X | – | 2012 | `50-X` style, comment fc:622 |
| 27 | `Wolverine 050-X (2010).cbr` | Wolverine | 50-X | – | 2010 | |
| 28 | `Secret Wars #Alpha (2015).cbz` | Secret Wars | Alpha | – | 2015 | pure-alpha needs `#` (fc:554-560) |
| 29 | `Batman Black and White 03 (2013).cbz` | Batman Black and White | 03 | – | 2013 | `BLACK`/`WHITE` in exceptions must not fire mid-title — guard |
| 30 | `Gideon Falls Director's Cut 1 (2018).cbz` | Gideon Falls | 1 Director's Cut | – | 2018 | bespoke rule fc:507-517; arguably issue=1 + edition |
| 31 | `Batman 39 (of 52) (2017).cbz` | Batman | 39 | – | 2017 | `(of N)` flags 39 (fc:576-595) |
| 32 | `Kick-Ass 3 01 (of 08) (2013).cbz` | Kick-Ass 3 | 01 | – | 2013 | count wins over `3` |
| 33 | `Empowered 01 (of 7.3) (2015).cbz` | Empowered | 01 | – | 2015 | decimal count (fc:406-433) |
| 34 | `Descender 011 (2 covers) (2016).cbz` | Descender | 011 | – | 2016 | covers token dropped (fc:597) |
| 35 | `Saga 55 (2018) (digital) (36p ctc).cbz` | Saga | 55 | – | 2018 | page tag merged (fc:436-449) |
| 36 | `Lazarus 01 (2013) (1440px).cbz` | Lazarus | 01 | – | 2013 | px dropped (comment fc:408) |
| 37 | `Batman v2 015 (2012).cbz` | Batman | 015 | v2 | 2012 | |
| 38 | `Batman Vol. 2 015 (2012).cbz` | Batman | 015 | v2 | 2012 | `vol.` + separate number (fc:727) |
| 39 | `Batman Volume 2 015 (2012).cbz` | Batman | 015 | v2 | 2012 | |
| 40 | `Justice League v2017 021 (2018).cbz` | Justice League | 021 | v2017 | 2018 | volume-as-year (sf:533-546) |
| 41 | `Iron Man v5 023 (2013).cbz` | Iron Man | 023 | v5 | 2013 | |
| 42 | `Astonishing X-Men Part 2 (2018).cbz` | Astonishing X-Men | – | v2 | 2018 | Mylar: `part` ⇒ volume (fc:742) — replacement should treat as issue/chapter cue instead |
| 43 | `Sandman Vol III 05 (1991).cbz` | Sandman | 05 | vIII (desired v3) | 1991 | Mylar: roman numeral discarded, vol lost (fc:753-757) |
| 44 | `Casper (1953-) 001.cbz` | Casper | 001 | v1953 | – | trailing-dash year = volume (fc:496-500) |
| 45 | `Saga TPB v01 (2013).cbz` | Saga | 01 | v01 | 2013 | TPB; issue:=volume (fc:829-842) |
| 46 | `Monstress Vol. 06 (2021) (Digital) TPB.cbz` | Monstress | 06 | v06 | 2021 | TPB |
| 47 | `East of West TPB (2014).cbz` | East of West | 1 | v1 | 2014 | TPB, no vol → both default 1 (fc:838-842, :1083) |
| 48 | `Watchmen HC (1988).cbz` | Watchmen | – | v1 | 1988 | HC (fc:847-849) |
| 49 | `Blacksad GN (2010).cbz` | Blacksad | – | v1 | 2010 | GN (fc:844) |
| 50 | `Pride of Baghdad Graphic Novel (2006).cbz` | Pride of Baghdad | – | v1 | 2006 | desired GN; Mylar: two-word `graphic novel` can never match a single token — dead code |
| 51 | `Kill or be Killed v1 (2017) (Digital TPB).cbz` | Kill or be Killed | 1 | v1 | 2017 | `digital tpb` (fc:829) |
| 52 | `Superman Smashes the Klan 2020 (2020).cbz` | Superman Smashes the Klan 2020 | – | v1 | 2020 | one-shot rule: number==year ⇒ title (fc:1149-1157), booktype TPB/GN/HC/One-Shot |
| 53 | `Batman Annual 02 (2017).cbz` | Batman | Annual 02 | – | 2017 | annual rewrite (fc:1283-1299) |
| 54 | `Wolverine 1997 Annual.cbz` | Wolverine | 1997 annual | – | 1997 | `year annual` (fc:1290-1297) |
| 55 | `Batman Annual 2021 (2021).cbz` | Batman | 2021 | – | 2021 | annual + year-as-issue, booktype stays issue (fc:1153-1155, :1309-1323) |
| 56 | `Deadpool BiAnnual 01 (2014).cbz` | Deadpool | BiAnnual 01 | – | 2014 | matchIT path (fc:1576-1579) |
| 57 | `Gotham City Sirens Special 1 (2022).cbz` | Gotham City Sirens | Special 1 | – | 2022 | (fc:1300-1307) |
| 58 | `Archie Summer Special 3 (1996).cbz` | Archie | Special 3 (Summer?) | – | 1996 | seasons in exceptions; behavior fuzzy — regression pin |
| 59 | `Justice League Dark 016 (2019) (Webrip) (The Last Kryptonian-DCP).cbz` | Justice League Dark | 016 | – | 2019 | scangroup `The Last Kryptonian-DCP` (rippers `-dcp`) |
| 60 | `Invincible Iron Man 019 (2016) (Digital) (Minutemen-Faessla).cbz` | Invincible Iron Man | 019 | – | 2016 | scangroup `Minutemen-Faessla` |
| 61 | `Southern Bastards 09 (2015) (digital) (Son of Ultron-Empire).cbr` | Southern Bastards | 09 | – | 2015 | scangroup `Son of Ultron-Empire` |
| 62 | `Batman.Annual.02.2017.digital.Glorith-HD.cbz` | Batman | Annual 02 | – | 2017 | Glorith dot-name hacks (fc:315-331, :938-952) |
| 63 | `023-Batman 404 (1987).cbz` (story-arc mode) | Batman | 404 | – | 1987 | reading_order.sequence=023 (fc:273-283) |
| 64 | `Batman - The Long Halloween 05 (1997).cbz` | Batman - The Long Halloween | 05 | – | 1997 | alt_series=`Batman`, alt_issue=`The Long Halloween` (fc:1167-1197) |
| 65 | `Daredevil 600 - Mayor Fisk (2018).cbz` | Daredevil | 600 | – | 2018 | trailing title after dash; dash_numbers demotion (fc:987-994) |
| 66 | `Batman 404 [__123456__] (1987).cbz` | Batman | 404 | – | 1987 | issueid=123456 (fc:346-354) |
| 67 | `Scott Pilgrim & The Infinite Sadness v3 (2006).cbz` | Scott Pilgrim & The Infinite Sadness | – | v3 | 2006 | `&` sentinel round-trip (fc:396-399); `Infinite` must not trip float('inf') — guard (fc:788-790 uses exact float parse, `infinity` only) |

Additional deliberate edge rows for the regression suite (expected per a *correct*
parser; Mylar behavior noted):

| # | Filename | Expected | Mylar3 behavior |
|---|----------|----------|-----------------|
| 68 | `Batman 404 (1987).CBZ` | parse normally, type=cbz | extension check not lowercased in parseit (fc:262) → filetype `unknown`, `.CBZ` not stripped |
| 69 | `Batman_404_(1987).cbz` | issue 404, year 1987 | `_` is a split char — works |
| 70 | `Batman,404,(1987).cbz` | issue 404 | `,` split char — works |
| 71 | `Teen Titans v1 Annual 1 (1967).cbz` | Annual 1, v1, 1967 | annual+volume interplay — pin behavior |
| 72 | `Star Wars Legacy II 03 (2013).cbz` | series `Star Wars Legacy II`, issue 03 | roman numeral II mid-title must survive |
| 73 | `Berserk v01 c01-05.cbz` (manga-style) | vol v01, chapter range | unsupported; `c01-05` mangled |
| 74 | `Preacher 01-66 Complete.cbz` | issue range 01-66 or reject | range not modeled; picks 66 or 01 unpredictably |
| 75 | `4001 A.D. 001 (2016).cbz` | series `4001 A.D.`, issue 001 | leading 4-digit non-year + dotted abbreviation — likely misparses |

---

## 4. Known weaknesses / bugs worth fixing

1. **Literal `'\s'` bug**: `modfilename.find('\s')` (filechecker.py:286) searches for a
   literal backslash-s, never found, so `modspacer` is *always* `.` — the
   bracket-spacing repair inserts dots into space-formatted names. Confirmed by
   inspection; the space branch is dead code.
2. **Extension handling**: not case-insensitive in `parseit` (":262); extension
   removed via unescaped regex `re.sub(filetype, '', filename)` (":270) so `.` matches
   any character and all occurrences are replaced; extension list hardcoded in two
   places; no `.cbt`.
3. **Index-based token arithmetic**: pervasive `split_file.index(sf)` returns the
   *first* occurrence, so repeated tokens (e.g. `Batman 66 66 (2016)`, a series whose
   title repeats a word/number) corrupt positions. The whole
   position/mod_position/highest_series_pos bookkeeping is the largest source of
   fragility.
4. **Hardcoded scan-group list** (":112): only five ripper substrings; anything else
   is unrecognized. A replacement should treat *any* trailing parenthesized/bracketed
   group that isn't a date/count as a tag, and keep a group whitelist only for
   disambiguation.
5. **Single-letter issue exceptions** (`A,B,C,X,O`) invite false positives (cover
   variants `Cover B`, title initials); Mylar relies on adjacency accidents to avoid
   them.
6. **Roman-numeral volumes silently dropped** (":753-757); spelled-out volumes beyond
   `one..six` also unsupported (":695).
7. **`part` ⇒ volume** (":742-751) conflates chapter/part numbering with volume; also
   gated on the watch title, so parse results differ by mode.
8. **Year window hacks**: `'19' or '20' in token` (":492) breaks for 18xx reprints and
   any future `21xx`; the `fulldate` branch of `checkthedate` hardcodes `1970 < year
   < 2020` (":1849) — already wrong for 2020+ dates.
9. **`%Y%m` in date formats** means a 6-digit issue number like `202004` validates as
   a date; conversely month-name cover dates `(June 2019)` are split into tokens
   before `checkthedate` can see them.
10. **Sentinel scheme** (`XCV`, `c11/f11/g11/h11`): filenames legitimately containing
    those substrings are corrupted; multiple distinct unicode segments are restored
    with `re.sub(...,1)` in a loop that can mis-assign them (":1236-1247, :562-571
    overwrites `tmpissue_number` per segment).
11. **`infinity` token parses as `float('inf')`** and depends on token position ≤2 to
    stay in the title (":788-790) — `Series Infinity 2021` style names misparse.
12. **First-`#` assumption**: `modfilename.find('#')` (":674) uses the first `#` in
    the whole name even when the matched token was a later one.
13. **Range issues** (`1-2`, `112/113`) unsupported in the parser and handled in
    `issuedigits` by *hardcoded literals* (helpers.py:1213-1228); ord-sum scoring for
    alpha suffixes can collide (different suffixes → same ord total) and mixes
    magnitude domains (`*1000` ints vs ord sums vs sentinels `9999999999` /
    `999999999999999`).
14. **Booktype gaps**: `graphic novel`/`hardcover` two-word forms unreachable;
    `one-shot`/`OS` never detected from filename; `TPB/GN/HC/One-Shot` is an
    ambiguous union value that callers must special-case.
15. **No publisher/edition model**: `(Digital)`, `(Webrip)`, `c2c`, `Deluxe Edition`
    etc. survive only by luck of the title boundary; `digital tpb` is a one-off.
16. **Config/state coupling & impurity**: behavior depends on `mylar.CONFIG`
    (`ANNUALS_ON`, `READ2FILENAME`, `IGNORE_SEARCH_WORDS`), on watch-mode vs
    justparse, and on module globals; results are not reproducible in isolation and
    are untestable — indeed there are **zero tests**.
17. **Silent failure semantics**: on failure a partial dict with
    `parse_status: 'failure'` is returned (":1334-1351); there is no confidence score,
    no explanation of *what* failed, and two different status keys
    (`parse_status`/`process_status`) leak to callers (":160-165).
18. **Duplicated, divergent re-implementations** of issue normalization in at least
    four places (helpers.rename_param, helpers.issuedigits, PostProcessor,
    filers.py, importer.py) — e.g. `NOW` handling differs slightly between them.
19. **Bracketed metadata**: `[...]` groups are tokenized whole (":404) but then have
    no semantics except the `[__id__]` case; common tags like `[Digital]`,
    `[1920px]`, `[Empire]` are unmodeled.
20. **`match_type` never populated**; `alt_series`/`alt_issue` heuristics are
    hyphen-position-based and break on series with hyphens beyond the first word.

---

## 5. Candidate requirements for the replacement (prose, grouped)

### Tokenization & normalization
- The parser shall accept a bare filename (with or without extension) plus an optional
  relative directory path, and shall be a pure function: identical input yields
  identical output with no dependence on global configuration, watchlists, or clock
  (the current-year cutoff for future-year rejection shall be an explicit parameter).
- The parser shall treat spaces, underscores, dots (when dots are the dominant
  separator, as in NZB names), and commas as token separators, and shall preserve
  parenthesized and bracketed groups as atomic annotation tokens.
- The parser shall handle Unicode natively (NFC/NFKD-aware comparisons, em/en dashes,
  curly quotes, fraction glyphs `½ ¼ ¾`, `∞`) without sentinel-substitution schemes,
  and shall never corrupt titles containing arbitrary ASCII substrings.
- The parser shall recognize comic archive extensions case-insensitively (`cbz`,
  `cbr`, `cb7`, `cbt`, `pdf` at minimum) and strip exactly the trailing extension.

### Issue numbers
- The parser shall recognize plain integer issues (with arbitrary zero-padding),
  `#`-prefixed issues, decimal issues (`15.5`, `.5`, `0.1`), negative issues (`-1`),
  unicode fraction issues (`½` etc.), and glued or space/dot-separated alphanumeric
  suffixes from a configurable exception vocabulary (AU, AI, INH, NOW, BEY, MU, HU,
  LR, DEATHS, ALPHA, OMEGA, seasonal names, Director's Cut), normalizing each to a
  canonical form.
- The parser shall not classify a leading numeric token as the issue number when it
  begins the title (e.g. `100 Bullets`, `52`, `2000AD`).
- The parser shall use mini-series count markers (`(of 12)`, `01 of 8`, including
  decimal totals) to anchor the issue number, and shall strip cover-count (`2 covers`)
  and page/quality tags (`36p ctc`, `1440px`) without treating them as issues.
- The parser shall support issue ranges (`001-002`, `112/113`) by either representing
  them explicitly or rejecting them with a distinct diagnostic — never by hardcoded
  per-title literals.
- Issue-number ordering keys shall be total, collision-free within the supported
  vocabulary, and shared by exactly one implementation used for parsing, matching,
  and renaming.

### Volumes
- The parser shall recognize volume designators `v2`, `V2`, `v02`, `vol 2`, `vol.2`,
  `vol. 2`, `volume 2`, `v2013` (4-digit = volume-year), roman-numeral volumes
  (`Vol III`), and year-range forms (`(1953-)`, `(1953-1959)`), distinguishing
  ordinal volumes from volume-years in the output.
- The parser shall distinguish trade volume numbers (where a TPB's "issue" is the
  volume) from ongoing-series volume labels, and shall not misinterpret `Part N` as a
  volume.

### Dates & years
- The parser shall extract cover years from `(1987)`, bare years, `YYYY-MM`,
  `YYYY-MM-DD`, and month-name forms (`(June 2019)`), preferring the right-most
  plausible date, rejecting years in the series-title region, and treating years more
  than one year in the future as title content — with the century windows covering at
  least 1900–2099 and no hardcoded upper bounds.
- When the only numeric candidate equals the detected year (`Title 2023 (2023)`), the
  parser shall classify the work as a one-shot/annual-style book rather than issue
  #2023, per the rules for annuals below.

### Annuals, specials & book types
- The parser shall detect `Annual`, `Special`, `BiAnnual` (and combined `1997 Annual`
  forms) as issue-classification markers, exposing them as a structured field rather
  than string-prefixed issue numbers, while removing them from the series title.
- The parser shall classify book type from filename cues — single issue (default),
  TPB (`TPB`, `digital TPB`, `trade paperback`), graphic novel (`GN`,
  `graphic novel`), hardcover (`HC`, `hardcover`), one-shot — as distinct enum values
  (no `TPB/GN/HC/One-Shot` union), defaulting the trade volume to 1 only when
  explicitly a trade format.

### Tags, groups & pass-through metadata
- The parser shall extract release/scanner group tags from trailing parenthesized or
  bracketed groups generically (last non-date, non-count annotation), with no
  hardcoded group list required for correctness.
- The parser shall recognize edition/quality annotations (`Digital`, `Webrip`, `c2c`,
  `Deluxe Edition`) as annotations excluded from title, issue, and volume.
- The parser shall extract embedded issue identifiers in the `[__<id>__]` convention
  and support story-arc reading-order prefixes (`NNN-`), returning both as structured
  fields.

### Series title & matching support
- The parser shall return the series title exactly as present (minus consumed
  designators), a normalization-folded variant for matching, and any alternate
  series/issue-title split implied by hyphen-delimited titles, without destroying
  titles whose first word contains a hyphen.
- Title-boundary determination shall be by grammar/priority rules over the token
  stream, not by mutable index bookkeeping over repeated-token-unsafe `list.index`
  calls.

### Quality, diagnostics & testing
- Every parse shall yield either a structured success (all fields typed, optional
  fields explicitly null) or a structured failure carrying the reason and partial
  fields under a single status vocabulary; parsers shall optionally emit a confidence
  score and the token classification trace for debugging.
- The parser shall be exhaustively covered by a table-driven regression corpus
  (seeded from Section 3) in which every behavioral rule above has at least one
  positive and one adversarial case, and shall be fuzz-tested to guarantee no input
  raises an unhandled exception (Mylar wraps whole passes in bare `except` today).
- Parsing of directory names (series folders like `Batman (2016)`) shall reuse the
  same engine with a mode flag, and results shall state whether each field came from
  the filename or the folder.
