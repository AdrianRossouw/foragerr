# import-regrouping — Library Import on a curated library

**Status:** pre-design. NOT an approved implementation change. It exists to be
read and approved by the owner (FRG-PROC-009) before any proposal is written;
at that point it decomposes into the three changes in
[Decomposition](#decomposition) — each with its own proposal, approval, and
registry IDs, the way the M6/M7/M11 pre-designs decomposed.

## Context

Library Import was designed (M2, `m2-existing-library-import`, FRG-IMP-023)
against a library shaped like the one foragerr itself creates: one folder per
series, one series per folder, files named descriptively inside it. The owner's
real library is not shaped that way. It is a **reading-order curation tree**:
series are nested inside arc/collection folders that carry an ordering prefix,
and the same series recurs in many of them.

```
/comics/Dark Horse/HellboyBPRD_CompleteSeries/05 - HELLBOY - THE MIDDLE YEARS/1997 Ghost -.../file.cbz
```

Run against that root, the feature is — the owner's word — "basically
unusable". The mental model the screen violates is stated just as plainly:
**import should identify comics (files), not folders.**

That is the right model, and the code already half agrees with it: the scan
parses every file individually and `LibraryImportSource` pins the confirmed
series onto each candidate by id, not by path
(`backend/src/foragerr/importer/sources.py:401-407`). What breaks is the one
step between them — how a file's parse becomes a *group key*.

## Evidence

### Measured on the live scan of the owner's root (2026-07-30)

| Measurement | Value |
|---|---|
| Staged groups from one root | **580** |
| Sample examined | 200 groups |
| …carrying a leading order-number in the matching key (e.g. `01 ghost hellboy`) | **104 / 200** |
| …holding a single file | **141 / 200** |
| …whose proposal scored below 0.7 | **141 / 200** |
| One real series, shattered | Superman ×14, Action Comics ×14, Adventures of Superman ×13, Man of Steel ×13 |

Four titles account for **54 of the 580 groups**. A group is supposed to be a
would-be series; 70% of them holding exactly one file says they are not series
at all.

### Root cause: three mechanisms, not one

Reproduced against the shipped parser and evidence layer (`ParseMode` per
layer, `reference_year=2026`):

```
'02 - Superman 001.cbz'   filename  key='02 superman'   conf=0.6
'Superman 001.cbz'        filename  key='superman'      conf=0.6
'023-Batman 404 (1987).cbz' filename key='023 batman'   conf=0.8
'05 - HELLBOY - THE MIDDLE YEARS'  folder  key='05 hellboy middle years'

file='01.cbz'      folder='Superman (1987)'  -> key='01'       provenance=file_name
file='scan001.cbz' folder='1997 Ghost - ...' -> key='scan001'  provenance=file_name
```

**M1 — the leading-title guard preserves curation ordinals inside the series
title.** `backend/src/foragerr/parser/__init__.py:508`:

```python
if t.index == 0 and not cand.anchored:
    continue  # leading-title guard (FRG-IMP-007)
```

A numeric token at position 0 that is not `#`-anchored is never an issue
candidate, so it survives into the title region
(`parser/__init__.py:730`) and into `matching_key`
(`parser/__init__.py:945`). The guard is *correct* — it is what keeps `52` and
`100 Bullets` parsing — but under a curation prefix it makes the ordinal part
of the series identity. This is precisely the owner's `01 ghost hellboy`, and
it is the whole explanation for Superman ×14: fourteen curation positions,
fourteen keys.

It also explains the confidence column. A name yielding series + issue but no
year scores exactly 0.6 (`parser/__init__.py:932-941`); a well-formed
`Ghost-Hellboy 01 (1996).cbz` scores 0.8. **141/200 below 0.7 is not a
metadata-quality problem — it is a fingerprint of this defect.**

**M2 — the evidence merge takes the first layer that produces *any* string,
never the best one.** `backend/src/foragerr/importer/evidence.py:118-128`
walks the fixed order (grab > file > folder > client) and returns the first
non-`None` value. Every layer's `ParseResult` carries a `confidence`, and
`pick()` never compares them. So `01.cbz` (confidence 0.35, no word in it at
all) beats the folder `Superman (1987)` (confidence 0.55) that was carrying the
answer. The FRG-PP-004 order is a *tiebreak masquerading as a ranking*.

**M3 — the folder fallback only fires on total parse failure.**
`backend/src/foragerr/library/flows/library_import.py:280-284` reaches for the
folder name only when `evidence.matching_key is None`. `'01'` and `'scan001'`
are "successful" parses, so the rescue never runs.

**Net effect.** The group key is one arbitrary string per file. Because the
curation ordinal is unique per curated folder, one key per folder falls out of
that arbitrariness — which is exactly what the owner observes and reasonably
names "grouping by folder". The code contains no `group by folder` step; the
folder identity is an *emergent artefact* of M1–M3.

### What the reference notes say

- **Mylar3 does not group by folder either.** Only the filename is parsed; the
  subdirectory is passed through as `sub` and never used for identity
  (`docs/research/mylar-filename-parsing.md:259-260`), and staged import
  results are grouped by the parsed dynamic name
  (`docs/research/mylar-feature-surface.md:192-197`). Its one folder-parsing
  path is a substitution when an NZB name is absent, not a rung in a ladder
  (`mylar-filename-parsing.md:263-266`).
- **Mylar3 already strips exactly the prefix we need.** §2.14 reading order:
  with a story-arc context, a leading `NNN-` (≤3 digits before the first
  hyphen) is stripped and returned as structured `reading_order`
  (`mylar-filename-parsing.md:287-291`, regression row 63 at line 384).
- **Sonarr aggregates evidence rather than ordering it.**
  `AggregateEpisodes` chooses "the best ParsedInfo among file/folder/
  download-client-title" (`docs/research/sonarr-architecture.md:412-419`), and
  `MatchesFolderSpecification` validates a file against its folder's parse
  rather than trusting either blindly (`sonarr-architecture.md:434`).
  Its per-series `DiskScanService` runs unmapped files through the same
  ImportDecisionMaker as downloads (`sonarr-architecture.md:468-474`).
- **Neither reference aggregates identity across sibling folders.** The
  ancestor-climbing rung proposed below is ours, and has no prior art in the
  notes.
- **We have already met the downstream half of this.**
  `docs/research/m9-user-sim-findings.md:113-117` (F8b): "A group's series path
  is the scanned folder… A flat multi-series folder can never import more than
  one series." The M11 pre-design's item 4 is the same gap seen from the other
  side (`openspec/changes/m11-import-intelligence-predesign/proposal.md:58-62`).

### Cost today

Each group costs one live, politeness-gated `search_series` on the
`interactive` lane, capped at `library_import_proposal_cap = 50` per run
(`backend/src/foragerr/config.py:1009`, `library_import.py:622-645`).
**580 groups = 12 scan runs** before every group has even been offered a
proposal.

## Goals

1. A group is a **series**, aggregated across every folder its files live in.
2. The folder is a **hint** — consulted when the filename carries no series,
   never allowed to invent an identity the files contradict.
3. Curation idioms (ordering prefixes, year folders, `Vol N` folders) are
   understood rather than absorbed into the key.
4. The review surface reads at series scale, not at 580-card scale.
5. Existing decisions survive the re-keying.

## Non-goals — what this must NOT change

- **FRG-IMP-028 read-only-root in-place semantics.** A read-only root forces
  `in_place = True` and hard-zeroes `rename_enabled`,
  `comicinfo_tag_enabled`, and `convert_cbr_to_cbz`
  (`library_import.py:832-841`, `931-941`). Untouched, and the fail-closed
  placement guard stays the backstop.
- **FRG-PP-022 and its three refusal guards** (`importer/decisions.py:47-50`,
  `179-215`). Regrouping changes what a *group* is; it does not change how a
  file resolves to an issue inside a confirmed series, and the ordinal
  fallback stays operator-only.
- **Review-first posture (FRG-IMP-023).** No auto-import, no auto-pick; the
  similarity floor stays (`library_import.py:401-435`).
- **FRG-IMP-005 single-fold rule.** No second `matching_key` implementation
  anywhere. The prefix strip happens *before* the fold, inside the parser,
  under a flag.
- The shared `import_candidate` pipeline, `LibraryImportSource`'s two-way
  series pinning, the safety specs, and history events.

## Decisions

Each decision carries a recommendation. Those marked **OWNER** need a call
before the proposals are written.

### D1 — Identity is the parsed file series, aggregated across folders

Group by the parsed **file** series fold, aggregated across every folder;
demote the folder to a hint consulted through the ladder in D4.

**Recommend: yes.** It is the owner's stated model, it is what Mylar3 does,
and the import machinery is already file-addressed.

### D2 — Strip the curation ordinal in the parser, delimiter-gated

The prefix must die at the key. Two places it could:

- **(a) In the parser**, activating **FRG-IMP-025** — *already approved*, sitting
  in Backlog, and specified as exactly this shape: "a leading reading-order
  prefix (`NNN-`, ≤3 digits before the first hyphen)… returning the sequence
  number as a structured field and excluding it from the series title"
  (`openspec/specs/imp/spec.md:642-653`).
- **(b) In the import grouping layer only** — a second normalization step,
  which FRG-IMP-005 forbids in spirit even if it dodges the letter.

**Recommend (a), mode-gated via `ParseOptions`**, enabled by the library-import
scan. FRG-IMP-025 exists for this and needs no new ID.

**The discriminating rule, empirically validated.** Strip only when the leading
digits are immediately followed by an explicit ordering delimiter — `-`, `.`,
or `_` (optional surrounding space) — and alphabetic content remains after it.
Every real numeric title in the wild uses a **bare space** or `#`; every
curation idiom uses a delimiter:

| Name | Today | Under the rule |
|---|---|---|
| `52 #12.cbz` | `52` | `52` (unchanged) |
| `100 Bullets 01.cbz` | `100 bullets` | `100 bullets` (unchanged) |
| `2000 AD 2145.cbz` | `2000 ad` | `2000 ad` (unchanged) |
| `30 Days of Night 03.cbz` | `30 days of night` | `30 days of night` (unchanged) |
| `023-Batman 404 (1987).cbz` | `023 batman` | `batman`, sequence 23 |
| `01. Superman 001.cbz` | `01 superman` | `superman`, sequence 1 |
| `03_Batman 12.cbz` | `03 batman` | `batman`, sequence 3 |
| `05 - HELLBOY - THE MIDDLE YEARS` | `05 hellboy middle years` | `hellboy middle years`, sequence 5 |

The rule never fires on a bare-space numeric title, so FRG-IMP-007's
leading-title guard keeps doing its job untouched.

### D3 — A filename with no word in it is not a series name

Narrow M2's fix rather than re-ranking the whole evidence stack: in `pick()`
for the **series field only**, a layer whose series name contains **no
alphabetic token** (`01`, `001`, `page 3`) does not satisfy the pick — fall
through to the next layer. Provenance records the layer that actually won.

The broader alternative — rank all layers by `ParseResult.confidence` with the
fixed order as tiebreak — is more principled and more dangerous: it changes
grab-record and download-client behaviour on paths this problem never touches.

**Recommend the narrow rule now**, and note the confidence-ranking idea as a
separate future question. This is a **MODIFIED FRG-PP-004** either way.

### D4 — The fallback ladder

Ordered, and stated so an operator can predict it:

1. **Filename**, ordinal-stripped, if it yields a series name with an
   alphabetic token → key, provenance `file_name`.
2. **Immediate parent folder**, ordinal-stripped, same test → key, provenance
   `folder_name`. *(Fixes `01.cbz` inside `Superman (1987)`.)*
3. **Nearest qualifying ancestor**, climbing toward but never reaching the
   root, first one yielding an alphabetic key wins → provenance
   `ancestor_folder`. Bound the climb (recommend 3 levels) and skip
   non-identifying ancestors — a bare year (`1997`), a `Vol N` folder (which
   parses to *no* key today), a publisher folder. *(Fixes
   `…/Superman (1987)/Vol 3/01.cbz`.)*
4. **Otherwise** today's behaviour: fold the parent folder name literally,
   stage `no_match` with a visible message, never drop the files
   (`library_import.py:280-284`, `341-347`).

Rung 3 is new and has no prior art in the reference notes; it is the rung that
makes a curation tree legible.

### D5 — Series path for a group that spans folders — **OWNER**

The hard one, and the reason this cannot ship as a parser patch.

Today `_GroupDraft.folder` is `os.path.commonpath(parents)`
(`library_import.py:249-251`), and in `in_place` mode that folder becomes the
series `path_override` (`library_import.py:900`). Two things then guard it: the
root-swallowing rail, which blocks when the common path *is* the root
(`library_import.py:848-863`), and `add_series`' path uniqueness
(`backend/src/foragerr/library/flows/add.py:207`).

Aggregating across folders makes `commonpath` climb. For Superman spread across
fourteen curation trees it will frequently land on the root — so **every
regrouped series would block with "group has no dedicated folder"**. Regrouping
without addressing this makes the feature *differently* unusable.

Options:

- **(a) Deepest common ancestor when it is strictly below the root and
  unclaimed; otherwise the rendered naming-template path under the root** — a
  *nominal* folder that need not exist on disk. Files are addressed
  individually by `issue_files.path` regardless; the series path is only an
  `add_series` uniqueness key plus the per-series rescan walk root
  (`backend/src/foragerr/library/flows/rescan.py:123`).
- **(b) Keep the rail as-is and refuse multi-folder groups.** Honest, and
  useless here.
- **(c) Move mode only** — consolidate each series into a real folder. Correct
  by construction, and flatly incompatible with a read-only reference root and
  with a curation tree the owner maintains by hand.

**Recommend (a)**, with the consequence stated out loud: a series whose files
span folders has no folder of its own, so **its per-series rescan must be
skipped** rather than walking a nominal path and finding nothing. That posture
is the owner call. The root-swallowing rail keeps an explicit test either way.

### D6 — Review surface at series scale

After regrouping, rows get *fewer and deeper*: one series, N files across M
folders. The current screen is a plain non-virtualized `groups.map` card list
with no select-all (`frontend/src/screens/library-import/LibraryImport.tsx:286-302`,
`384-514`) whose hook walks every server page up front
(`libraryImportHooks.ts:55-78`). At 580 it is already the wrong shape.

The machinery to copy exists and is proven at 1318 items on the sources review
screen:

- `@tanstack/react-virtual` `useVirtualizer` with `measureElement` dynamic row
  heights, stable `getItemKey` (`screens/sources/StoreManage.tsx:204-225`);
- one flat `ReviewItem[]` union of `group-header | row` so selection, the
  shift-range anchor, and the virtual window index the same array
  (`screens/sources/reviewGroups.ts:52-60`, `226-296`), with
  `COLLAPSE_MIN_ROWS = 3` (`reviewGroups.ts:24`);
- anchor-based shift-range selection over the flat index
  (`StoreManage.tsx:239-274`);
- a group header carrying counts, a status breakdown, "Match all…", and
  "Show N / Collapse" (`screens/sources/EntitlementGroupHeader.tsx:27-152`);
- one bulk endpoint applying each row in its own transaction with per-id
  partial-failure reporting (`backend/src/foragerr/api/sources.py:735-808`).

**Recommend: adopt all of it.** Proposed row: series title (proposal name, or
the parsed key when unmatched), the CV proposal chip, **"N files across M
folders"**, state chip; expand → the file list grouped by folder with each
folder path shown. Bulk: confirm every proposed group above a similarity
threshold in one call, via a `POST /library-import/groups/bulk` mirroring the
sources bulk shape.

**A split affordance is required, not optional** — see R2.

### D7 — Carrying decisions across the re-keying

`_carry_forward` is keyed on `matching_key`
(`library_import.py:300-347`), so changing the derivation **orphans every
carried decision**: a confirmed `01 ghost hellboy` will not carry to
`ghost hellboy`.

- **(a) Wipe.** Simple; costs the owner nothing they value, since the current
  staging is by their account unusable.
- **(b) Re-key.** Old rows keep their full file list
  (`backend/src/foragerr/library/models.py:418-420`), so re-derive the new key
  from each prior row's stored paths and carry its decision to the new group
  that inherits those files.
- **(c) Carry by `confirmed_cv_volume_id`.**

**Recommend (b), with (c) as the collision rule**: when several prior confirmed
rows land on one new group, carry the confirmation only if they **agree** on
`confirmed_cv_volume_id`; on disagreement leave the group `proposed` with a
visible message. The Superman ×14 case then resolves perfectly — fourteen prior
confirmations of one volume collapse into one.

Already-`imported` rows need no migration: imported files are filtered out at
replace time against `issue_files` (`library_import.py:599-618`), so imported
work is never re-staged.

### D8 — ComicVine budget after the regroup

Not a decision — a consequence worth quantifying, since CV discipline is a
standing constraint.

Today: 580 groups ÷ a 50-proposal cap = **12 scan runs**. The four measured
titles alone collapse 54 groups into 4. The 104/200 sample rate says roughly
half the corpus carries a shattering prefix, and 141/200 single-file groups
say the shatter is deep. Bounding it honestly:

| Collapse ratio | Groups after | Scan runs to full coverage |
|---|---|---|
| conservative 4:1 | ~145 | 3 |
| sample-implied ~8:1 | ~73 | 2 |
| measured-on-Superman 13.5:1 | ~43 | **1, under the cap** |

Even the conservative floor is a **4× reduction in live CV searches**, and the
likely outcome is that a curated root finishes proposing in a single run. The
cap, the floor, and the interactive lane all stay exactly as they are.

## Decomposition

Three gate-sized changes. **A** is shippable alone and delivers most of the
relief; **B** is what makes the regrouped result actually importable; **C** is
what makes it pleasant. IDs are indicative — allocate at each proposal
(the "allocate at *that* change's proposal" lesson).

### Change A — `import-regrouping-identity` (backend; IMP, PP)

The keying fix: D1, D2, D3, D4.

- **New:** `FRG-IMP-029` — series identity aggregated across folders, and the
  four-rung fallback ladder with its provenance vocabulary.
- **Activated:** `FRG-IMP-025` (approved, Backlog → implemented) — the
  reading-order prefix, mode-gated, sequence returned as a structured field.
- **MODIFIED:** `FRG-PP-004` (the no-alphabetic-token rule in layer selection);
  `FRG-IMP-023` scenario 1 (grouped by `matching_key` → grouped by aggregated
  series identity). MODIFIED deltas **restate the COMPLETE scenario set** — the
  v0.6.3 lesson.
- **Tests:** FRG-IMP-021 corpus rows for the whole D2 table (both columns —
  the unchanged numeric titles are the regression guard); scan tests for
  cross-folder aggregation and each ladder rung.
- **Gate:** medium (4–5 angles + Codex). The parser eats untrusted filenames,
  so confirm the existing STRIDE row for import parsing still covers it; no new
  listener, egress, or credential surface, no SOUP.

### Change B — `import-regrouping-placement` (backend; IMP, SER)

D5 and D7 — the riskiest change, touching series-path allocation and rescan.

- **New:** `FRG-IMP-030` — placement and series path for a group spanning
  folders, including the rescan posture; `FRG-IMP-031` — decision carry-forward
  across a re-keying, with the volume-agreement collision rule.
- **MODIFIED:** `FRG-IMP-023` (root-swallowing rail wording); `FRG-SER-021` /
  `FRG-SER-022` only if the rescan posture moves the read-only boundary — most
  likely it does not, since nothing here writes.
- **Tests:** the rail keeps an explicit "never becomes the root" test;
  multi-folder in-place import on a read-only root; the Superman-style
  fourteen-confirmations-collapse-to-one migration case.
- **Gate:** large. It changes what a series path *means*.

### Change C — `import-regrouping-review` (frontend + API; UI, API)

D6 plus the split affordance from R2.

- **New:** `FRG-UI-050` — series-scale library-import review (virtualized,
  collapsible, files-across-folders, bulk confirm, split); one `FRG-API-0NN`
  for the bulk group endpoint.
- **MODIFIED:** `FRG-UI-015`.
- **Gate:** medium. Include the a11y pass the review surfaces are held to.

**Sequencing:** A → B → C, though C can start as soon as A fixes the API row
shape.

## Risks

| | Risk | Mitigation |
|---|---|---|
| **R1** | Ordinal stripping eats a real numeric title (`52`, `2000 AD`, `100 Bullets`). | The delimiter rule, validated in D2's table; both columns pinned as corpus rows; mode-gated so only the library-import scan is affected. |
| **R2** | **Over-merging.** Two genuinely different series fold to one key — a v1 and a v2 run, or singles vs. the collected edition of one title. Folder-shatter was accidentally keeping them apart. `docs/research/m9-user-sim-findings.md:149-156` (F20) is this failure already observed. | The group is a *proposal*, so the review surface must let an operator **split** a group — hence "required, not optional" in D6. Booktype typing (FRG-UI-022) and the volume-issue-count sanity check help but do not substitute. |
| **R3** | Decoupling the series path weakens the root-swallowing rail. | Keep an explicit test that no import produces a series whose path is the root, under every D5 branch. |
| **R4** | The first regroup scan strands existing decisions. | D7's re-key migration; and imported files are already protected by the `issue_files` filter at replace time. |
| **R5** | **Broader search terms match the wrong volume.** `superman` returns far more candidates than `02 superman` did, and the 0.5 similarity floor is *easier* to clear on a wrong volume. | The floor stays and never auto-picks. Pair with the M11 pre-design's item 5 mismatch warning ("10 files, volume has 1 issue") — a regrouped 200-file Superman group proposing a 1-issue volume must say so loudly. |
| **R6** | A long climb up rung 3 attaches files to an ancestor that is a *publisher* or *collection*, not a series. | Bound the climb (3 levels), stop below the root, and record `ancestor_folder` provenance so the review surface can show *why* a group is named what it is. |

## Open questions for the owner

1. **D5 — the series path for a multi-folder group.** Nominal path + skipped
   per-series rescan (recommended), or refuse multi-folder groups, or require
   move mode? This is the decision that shapes change B.
2. **D7 — migration.** Re-key existing decisions (recommended) or wipe and
   re-review?
3. **Split affordance** — in scope for change C (recommended, per R2) or a
   follow-up?
4. **Scope of the ordinal strip.** Library-import scan only (recommended), or
   also the manual-import and completed-download paths? Those paths see release
   names, not curation names, so extending it buys little and risks more.
5. **Reading order as metadata — flagged as a future idea, explicitly NOT
   proposed here.** FRG-IMP-025 returns the stripped sequence as a structured
   field, so after change A the curation order the owner encoded in their folder
   names would be *available for free* rather than discarded. Storing it, and
   letting the library be browsed or an OPDS feed be ordered by it, is a real
   feature — and it belongs to the Backlog ARC area (story arcs), not to
   fixing import. **Recommendation: capture the field, build nothing on it, and
   raise it as its own idea if the owner wants it.**

## Impact if approved

- **Code:** `parser/` (prefix rule under a `ParseOptions` flag),
  `importer/evidence.py` (series-field pick), `library/flows/library_import.py`
  (ladder, cross-folder aggregation, `folder` derivation, carry-forward),
  `library/flows/add.py` + `rescan.py` (change B), `api/library_import.py`
  (bulk endpoint), `screens/library-import/` (change C).
- **Manual (FRG-PROC-011):** `docs/manual/user/import.md` — the "groups
  everything unmapped by normalized series name" description (around line 218)
  becomes the ladder; the folder-as-hint behaviour and the split affordance are
  both user-visible.
- **Security (FRG-PROC-006):** no new listener, egress, credential, or SOUP
  surface. The parser's untrusted-filename exposure is unchanged in kind;
  confirm the existing STRIDE row still covers the ancestor climb, which reads
  more path components than before but performs no new I/O and stays inside the
  bounded walk.
- **Traceability (FRG-PROC-004/005):** every new ID gets a tagged test;
  `FRG-IMP-025` moves from `approved` to `implemented` in
  `docs/traceability/requirements-registry.md`.
