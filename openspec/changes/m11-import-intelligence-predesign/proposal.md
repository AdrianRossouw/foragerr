# m11-import-intelligence-predesign

## Approval

**Milestone split approved by Adrian, 2026-07-16 (in session):** import
heuristics is promoted out of M9 into its **own milestone and release cycle**
("M11 import-intelligence"; M10 = go-live, M7 label reserved for torrents).
This document is the milestone **pre-design** — NOT an approved implementation
change. At milestone kickoff it decomposes into ~3 changes (parser/matcher
core, flat-folder placement, import-review UX), each with its own proposal,
approval, and registry IDs, the way M6/M7 pre-designs decomposed.

Milestone slotting (before M10 vs first post-1.0) is an open owner decision at
the milestone gate. A research phase precedes the decomposition: the **corpus
bake-off** — squash-invariant matching + DP segmentation vs publisher-filtered
corpus vs cover-hash verification (ComicTagger's algorithm, studiable in
`.reference/mylar3/lib/comictaggerlib/`), measured on the real 61-file Humble
corpus for series-hit / issue-attach / wrong-edition rates. A trained
segmentation model was considered and parked: the failure mode is systematic
squashing, which deterministic segmentation + squash-normalized ranking
handles without SOUP/traceability cost; revisit only if the bake-off reveals a
genuinely noisy long tail.

**Carve-out:** the corpus-reduction quick win (shipped default ignore list,
Settings UI, hide-with-count in Add New) ships in M9 as
`m9-publisher-ignore-defaults`; this milestone extends the same list to
import-proposal and cover-candidate filtering (item 5 below).

## Why

The M9 simulated-user run imported the owner's real 61-file Humble Bundle
corpus (13 series, flat folder, squashed filenames) through Library Import and
got **zero files in** — even after exhaustive manual correction — while the
same files renamed canonically imported flawlessly (findings F8–F10, F12, F13,
F15, F17, F20 in `docs/research/m9-user-sim-findings.md`). Store-sourced,
DRM-free files (Humble is a first-class source since M6) simply do not carry
scene-style names, so "get more heuristicy about mapping comics when filenames
aren't descriptive enough" (owner direction, 2026-07-15) is now the gap between
foragerr and its own headline use case. Three independent walls: unsegmented
names defeat the parser, flat folders defeat series-path allocation, and the
file→issue matcher ignores the match the user just confirmed.

## What Changes

1. **Filename tokenizer upgrades.** `_volN`/`volN`/`_issueN`/`issueN`
   (case/separator-insensitive) parse as number tokens and are excluded from
   the series key — `ignited_issue1.cbz` groups under `ignited` with issue 1,
   `carthago_vol5.cbz` under `carthago` with ordinal 5.
2. **Squashed-name segmentation fallback.** When a series key yields no
   ComicVine results, retry with segmentation candidates (dictionary/greedy
   word-split, known-prefix handling for `the`/`before`/possessives) before
   staging no-match — `beforetheincal` → "before the incal" (which CV matches
   today).
3. **Confirmed match constrains file matching.** A group's confirmed CV volume
   is authoritative for its files: match `volN`/`issueN`/bare-ordinal tokens
   against that volume's issue list (album-per-issue series map volN→issue N).
   No file in a confirmed group should fail with "unknown series".
4. **Flat multi-series folders import via placement.** When a group's files
   live in a folder shared with other groups, derive the series path from the
   folder-naming template (respecting existing-library-import mode: move —or
   copy— into per-series folders), instead of claiming the shared folder and
   colliding ("path already used by another series").
5. **Edition preference + sanity guards.** The publisher ignore list (shipped
   in M9 by `m9-publisher-ignore-defaults`) filters import-proposal and
   cover-candidate sets before scoring; proposal ranking prefers
   preferred-market publishers among what remains; a proposal whose volume has
   fewer issues than the group has files gets an explicit mismatch warning
   ("10 files, volume has 1 issue"); proposal cards and the inline picker show
   issue counts + descriptions (Add New parity) and dedupe identical rows.
6. **Same-title path disambiguation.** When a new series' rendered folder
   collides with an existing series (singles vs trades volume of the same
   title/year), disambiguate the folder automatically (naming-template
   collision suffix) and/or expose an editable path in the add dialog — the
   Collect As = Collected Editions flow must be addable next to the singles
   volume.
7. **Import-review UX.** Group cards show the parsed series key and an
   expandable file list; confidence renders only when it carries signal;
   the batch-options/Import bar is sticky; a failed add never leaves a
   zombie series shell (create-then-attach is atomic per group, or the shell
   is rolled back); per-group failure reasons are logged at WARNING.

## Non-goals

- No embedded-metadata (ComicInfo.xml) mining at scan time — separate idea.
- No fuzzy auto-accept: segmentation/preference only changes *proposals*;
  review-first import stays (FRG-IMP-023 posture).

## Impact

- Requirements: ~6–8 new IMP/SRCH/UI requirements (allocate at approval);
  MODIFIED deltas restate complete scenario sets (v0.6.3 lesson).
- Code: filename parser, library-import scan/group/execute flow, matcher,
  Add New search ordering, naming/folder rendering, LibraryImport UI.
- Tests: the Humble corpus filename shapes become fixture cases
  (squashed names, `_volN`, `_issueN`, flat folder, metabarons/metabaron
  adjacency, 1-issue-volume mismatch); regression: canonical names unchanged.
- Manual: `docs/manual/user/import.md` (grouping, segmentation, flat-folder
  placement, mismatch warning), `docs/manual/user/search.md` (ranking).
- Security: parser operates on untrusted filenames — extend existing STRIDE
  row for import parsing if segmentation adds new decode paths; no new
  listener/egress surface. SOUP: none expected (prefer stdlib segmentation;
  if a wordlist dependency is added it enters the SOUP register in-change).
