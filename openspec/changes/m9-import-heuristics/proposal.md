# m9-import-heuristics

## Approval

**DRAFT — pending owner approval (FRG-PROC-009).** Registry IDs not yet allocated.
Large scope; expect to split into 2–3 implementation changes at kickoff
(parser/matcher core, flat-folder import placement, import-review UX) the way
M6/M7 pre-designs decomposed.

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
5. **Edition preference + sanity guards.** Proposal ranking (and Add New
   search ordering) prefers preferred-market/English publishers and de-ranks
   or badges translations; a proposal whose volume has fewer issues than the
   group has files gets an explicit mismatch warning ("10 files, volume has 1
   issue"); proposal cards and the inline picker show issue counts +
   descriptions (Add New parity) and dedupe identical rows.
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
