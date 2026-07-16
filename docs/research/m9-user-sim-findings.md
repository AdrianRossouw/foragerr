# M9 simulated-user testing — findings report

**Date:** 2026-07-15/16 · **Build under test:** `foragerr:m9sim` from `main` @ `21ba049` (v0.9.10)
**Method:** four simulated reader personas driven through the real UI with Playwright against a
fresh container (empty `/config`), live ComicVine + NZB.su/DogNZB + SABnzbd + Newshosting, and
a real 61-file Humble Bundle corpus (`sample-comics/humble-files`, 13 series, squashed
filenames). One real usenet grab end-to-end. OPDS exercised with a simulated reader client
(feed walk, CBZ download, OPDS-PSE page streaming, image decode). A Codex second-opinion run
was attempted for the weekly-reader persona but its sandbox could not launch a browser or
reach the app; that persona was run by the orchestrator instead.

Personas: **novice first-run** (UI-only setup), **weekly superhero reader** (subscribe →
grab → read), **Humble collector** (library import of the real corpus), **trades/OPDS
reader** (collected editions + iPad reading).

---

## Executive summary

The product spine is in genuinely good shape: first-run setup through the UI is smooth
(indexer/download-client forms with live Test are exemplary), and the core loop — subscribe,
interactive search, real usenet grab, SAB download, import, **read the page over OPDS-PSE
within two minutes** — worked first try, fast, with a correct decision engine.

Three things stand between that spine and a good experience:

1. **The first-run killer is real and still present (F1).** A ComicVine key set through the
   UI never reaches background workers until the container restarts, so every fresh install's
   first series add fails with a bare "Refresh: failed" and 0 issues, while Health says
   ComicVine is OK. The only diagnosis is a Python traceback in Logs.
2. **Humble-style files are 100% unimportable (F8).** Three independent walls — unsegmented
   squashed names, flat-folder path collisions, and a file→issue matcher that ignores the
   user's own confirmed match — mean the realistic Humble drop imports **zero of 61 files**
   even after exhaustive manual correction. Renaming files canonically by hand makes
   everything work flawlessly, which localizes the gap precisely to naming heuristics.
3. **Edition disambiguation is the quiet data-quality trap (F9/F17/F20).** Foreign reprints
   outrank the wanted volume in Add New (a German Panini volume is the #1 result for
   "Ultimate Spider-Man"), import proposals hide issue counts so a 1-issue hardcover
   silently swallows a 10-volume series, and same-title volumes (singles vs trades) collide
   on folder paths so the trades workflow shipped in M3 cannot actually be exercised.

Recommended vehicles (drafts on this branch, pending FRG-PROC-009 approval):
`m9-cv-key-live-reload`, `m9-import-heuristics`, `m9-ux-diagnosability`.

---

## Triage table

| # | Sev | Area | Finding |
|---|-----|------|---------|
| F1 | **Critical** | Metadata/workers | UI-set ComicVine key invisible to workers until restart; first add fails opaquely |
| F8 | **Critical** | Import heuristics | Humble-style filenames unimportable: no segmentation, `_issueN`/`_volN` unparsed, flat-folder collisions, confirmed match unused by file matcher |
| F9 | Medium | Import quality | Wrong-edition proposals undetectable (no issue counts; no files-vs-volume-size sanity check); healthy-looking 1/1 series with 9 stranded files |
| F17 | Medium | Add New | Foreign reprints outrank the English volume (Panini Verlag #1 for USM; Marvel 9th) — F5 upgraded |
| F20 | Medium | Naming | Trades volume can't coexist with singles: `/library/Saga (2012)` path collision; no path override in add dialog |
| F2 | Medium | UX | Guidance errors name Settings but don't link; add-dialog root-folder dead end costs ~11 actions vs ~6 with inline picker |
| F16 | Medium | Calendar | Pull-source outage renders as plain "0 issues this week" — no degraded notice outside Health |
| F10 | Medium | Import UX | Flat-folder group cards all titled by folder; parsed key/files not shown; uniform 35% confidence adds no signal |
| F3 | Low | Frontend | Unknown SPA route (e.g. `/settings/media`) renders a fully blank page |
| F11 | Low | Observability | Import failures logged only as INFO totals; per-group reasons UI-only |
| F12 | Low | Import | Failed/blocked imports leave zombie series shells (created, 0 files, squatting the folder path) |
| F13 | Low | Import UX | Inline CV picker: no issue counts/descriptions; duplicate identical rows |
| F14 | Low | Design Q | Read-only path refused as root folder — blocks read-only NAS in-place libraries |
| F19 | Low | Activity | 60s track-downloads tick: fast grabs show an empty Queue until the next tick |
| F22 | Low | OPDS | HEAD on OPDS routes returns 404 JSON (some readers preflight HEAD) |
| F23 | Low | OPDS | File-less series appear as empty shelves to reader clients |
| F4 | Low | Health copy | `pull_source_url` config-key jargon in a UI-facing warning |
| F15 | Info | Import UX | Batch options + Import button live below 23 cards (sticky bar wanted); Monitor default silently makes imported series' gaps auto-wanted |
| F18 | Info ✅ | Pipeline | Grab→download→import→OPDS-readable in ~1m47s, fully automatic, SAB history cleaned |
| F21 | Info ✅ | OPDS | Feeds, MIME, byte-identical download, PSE with real page counts, crisp 1200px JPEG pages |
| F6 | Info ✅ | Settings | Indexer/DL-client add flows with live Test are excellent |
| F24 | Info ✅ | Resolved | Known "Wanted badge over-count" closed by design (Queue-only badge policy); Wanted page internally consistent |

(F5/F7 folded into F17/F2. Full narrative per finding below.)

---

## Detailed findings

### F1 · CRITICAL · ComicVine key set via UI never reaches workers (the first-run killer)

**Repro (fresh install):** Settings → General → paste key (Add New search works immediately)
→ add any series → series page shows **"Refresh: failed", 0 issues**. Health shows ComicVine
**OK**. Logs show `refresh-series … ComicVineAuthError: comicvine authentication failed
(HTTP 401)` (`metadata/comicvine.py:517` via `library/flows/refresh.py:115 get_volume`).
Restart the container → Refresh works (72 Saga issues in ~54s).

**Mechanism:** the request-path lookup client reads the live key; the worker-context client
is built with the boot-time (empty) key and never rebuilt after a config save.

**Why it matters:** this is the very first action every new operator performs after entering
the key. The failure is silent-ish (small status line), Health contradicts it, and the
workaround (restart) is undiscoverable. Matches the standing demo-finding
(CV-key-worker-snapshot); **not fixed as of v0.9.10**.

**Recommend:** workers resolve the key per-request (or subscribe to config changes); surface
refresh failure cause on the series page; make the ComicVine health component reflect
worker-side auth failures. → draft `m9-cv-key-live-reload`.

### F8 · CRITICAL · The Humble corpus is unimportable end-to-end

Corpus: 61 real cbz across 13 series, flat folder, Humble names (`theincal_vol5.cbz`,
`ignited_issue1.cbz`, `metabarons` vs `metabaron`). Three independent walls:

- **(a) Parser/segmentation.** Squashed names return no ComicVine results and stage as
  no-match: `theincal`, `beforetheincal`, `fourthpower`, `robertsilverbergscolonies`,
  `alexandrojodorowskysscreamingplanet`, `metabaronsgenesis castaka`, `spacebastardsissue1`
  — 7 of 13 series, even though every one exists on CV under its spaced name ("Before the
  Incal (2015) Humanoids" is right there). `_issueN` is not an issue token, so
  `ignited_issue1..4` became four separate one-file groups keyed `ignited issue1` etc. —
  12 junk groups from 3 series, each needing identical manual repair (fixing one sibling
  does not help the next). `_volN` is stripped for grouping but never mapped to an issue.
- **(b) Flat folder = path collision.** A group's series path is the scanned folder, so the
  first imported group claimed `/library/humble-files` and every other confirmed group
  failed `add failed: path '/library/humble-files' is already used by another series` —
  verified in both in-place and Move modes. A flat multi-series folder can never import
  more than one series.
- **(c) Confirmed match doesn't reach the file matcher.** In a clean per-series folder
  (`Carthago (2016)/`) with an operator-confirmed volume, every `carthago_volN.cbz` still
  blocked: *"could not match this file to a known series and issue."* The group's confirmed
  volume does not constrain per-file matching, and `volN` ≠ issue N.

**Measured:** auto-proposals correct for 2/13 series (18/61 files); after exhaustive manual
fixing, **0/61 flat files imported**. Control test: canonical rename (`The Incal 001
(2001).cbz` in `The Incal (2001)/`) → flawless (80% confidence, correct auto-proposal,
12 CV issues, 6 files attached). The gap is exactly the heuristics.
→ draft `m9-import-heuristics`.

### F9 · Medium · Wrong-edition proposals are undetectable

`metabaron` → proposed the **Spanish** Metabarón (Yermo Ediciones) over Humanoids' English
volume; `barbarella` → the **1964 French** original; `carthago` → "Carthago (2016)
Humanoids", which looks right and is actually the **1-issue hardcover**, so 10 files can
never attach — and after import the library shows a healthy green **1/1** while 9 files sit
stranded. Import cards show no issue count or description (Add New shows both), and the app
never flags the glaring "10 files vs 1-issue volume" mismatch.
**Recommend:** show issue counts/description on proposals and the inline picker; warn on
file-count > volume-issue-count; prefer English/preferred-market publishers in proposal
ranking. → `m9-import-heuristics`.

### F17 · Medium · Add New ranking favors foreign reprints (F5 upgraded)

"Ultimate Spider-Man" → #1 result **Panini Verlag (German) 2024**; Marvel's 2024 ongoing is
**9th**. "Saga" interleaves FR/DE/ES translations above relevant US volumes. A trusting user
subscribes to the wrong volume on the hottest current book.
**Recommend:** de-rank/badge translations (publisher market heuristic), or a language filter
chip. → `m9-import-heuristics` (same preference logic as F9).

### F20 · Medium · Singles + trades volumes of one series cannot coexist

Adding the Saga trades volume (Collect As = Collected Editions — the exact feature M3 built)
fails: `path '/library/Saga (2012)' is already used` — both volumes render the identical
folder from `{Series Title} ({Year})`, and the add dialog has no path override.
**Recommend:** disambiguate folder naming on collision (e.g. append `[Trades]`/CV id) or an
editable path in the add dialog. → `m9-import-heuristics` (naming), UI part in
`m9-ux-diagnosability`.

### F2 · Medium · Guidance errors are dead ends

- "ComicVine API key missing or invalid — check Settings." — not a link.
- Add dialog: "No root folders are registered… add … in Media Management settings first." —
  not a link, and resolving it means abandoning the dialog, configuring, returning,
  re-searching, re-opening: **~11 user actions vs ~6** with an inline root-folder picker
  (Sonarr pattern: picker + "add new path" inside the dialog).
→ `m9-ux-diagnosability`.

### F16 · Medium · Calendar hides the pull-source outage

With the weekly source genuinely down (Cloudflare 523 — a live outage during the run, which
also proved the degraded-health path works), the Calendar shows only *"Showing all 0 single
issues shipping this week"*. Nothing hints the source is down; the user concludes nothing
ships. **Recommend:** degraded-source banner on Calendar when pull-source health ≠ OK.
→ `m9-ux-diagnosability`.

### F10 · Medium · Import cards are unidentifiable on flat folders

All 23 cards were titled `humble-files /library/humble-files`; the parsed key appears only
inside no-match error text; proposed cards show no filenames at all (the two Metabaron
groups differed only as "6 files" vs "8 files"); confidence pinned at 35% for every
squashed name (the parser floor) adds no signal. **Recommend:** card shows parsed key +
expandable file list; confidence only when meaningful. → `m9-import-heuristics` (UI).

### Low / info

- **F3** Unknown SPA routes render a fully blank page (`/settings/media`) — no shell, no 404.
- **F11** `library-import: add-failed=5 blocked=1` is the *only* log line for five failures;
  reasons are UI-state only. Log per-group reasons at WARNING.
- **F12** Failed imports leave zombie series shells (created series, 0 files) that also
  squat the folder path and block siblings; delete-series flow itself is good.
- **F13** Inline CV picker: duplicate identical rows ("The Metabaron (2016) Humanoids" ×2,
  "Ignited (2019) Humanoids" ×2); no issue counts/descriptions.
- **F14** Read-only mounts are refused as root folders ("path '/humble' is not writable") —
  blocks read-only NAS in-place libraries. Decide + document.
- **F19** Fast grabs beat the 60s track-downloads tick; Queue looks empty mid-pipeline.
- **F22** OPDS routes 404 on HEAD (JSON body); readers/proxies that preflight HEAD break.
- **F23** File-less series render as empty OPDS shelves.
- **F4** Health warning tells a UI user to "verify 'pull_source_url'" (config jargon).
- **F15** Import batch bar (options + Import N selected) sits below the full card list —
  sticky placement wanted; Monitor default silently auto-wants imported series' gaps.
- **F7** Login page fires a console 401 (session probe); first CV search ~12s with a bare
  spinner.

### Positives worth keeping (F6/F18/F21/F24)

- Indexer + download-client add flows with live **Test** and concrete success messages.
- The whole acquisition chain: grab 00:19:59 → SAB accepted (category `comics`) → 93.9 MB
  downloaded < 60s → imported at the next tick (**~1m47s grab→library**) → correct series
  folder → History trail → SAB history auto-cleaned.
- OPDS: correct Basic realm, clean nav/series/issue feeds, correct comic MIME,
  byte-identical CBZ download, OPDS-PSE with real per-file page counts and crisp resized
  JPEG pages — the freshly-downloaded issue was iPad-readable ~2 minutes after Grab.
- The old "Wanted badge over-count" demo finding is **closed by design** (Queue-only badge
  policy, `wanted-count-consistency`); Wanted page counts are internally consistent.
- Verbatim rejection reasons + Approved/Grab decision surface in interactive search read
  clearly (reasons could be inline-visible rather than hover-only — nit).

---

## Recommendation → proposal mapping

| Vehicle | Carries | Status (2026-07-16) |
|---|---|---|
| `m9-cv-key-live-reload` | F1 (+ refresh-failure surfacing, health truthfulness) | **Approved** → v0.9.11 |
| `m9-publisher-ignore-defaults` | F17 (default ignore list, Settings UI, hide-with-count) | **Approved** → v0.9.12 |
| `m9-ux-diagnosability` | F2, F16, F3, F4, F11, F19, F22, F23, F14 (documented) + states-audit findings | **Approved** → v0.9.13 |
| `m11-import-intelligence-predesign` | F8, F9, F10, F12, F13, F15, F20(naming) | **Milestone split approved**; decomposes at its own kickoff after the corpus bake-off |

Approved by Adrian 2026-07-16 (in session, FRG-PROC-009); approvals recorded in each
proposal. Registry IDs are allocated at each change's implementation kickoff (M3 lesson:
allocate at the implementing change's proposal, never pre-allocate).

## Test-run state (for reproducing/cleanup)

Container `foragerr-m9sim` on `127.0.0.1:8791` (bound loopback-only), image `foragerr:m9sim`
(main @ 21ba049), config/library under the session scratchpad (`m9sim/`). Library: Saga
(0 files, 72 wanted), Carthago (wrong 1-issue HC volume — F9 exhibit), The Incal (6 files,
readable), Ultimate Spider-Man 2024 (#24 downloaded + imported + OPDS-verified). Indexers
deliberately left **interactive-only** (auto-search + RSS off) so the idle instance cannot
mass-grab the wanted backlog; GetComics pair still seeded-disabled; SABnzbd enabled.
`sample-comics/humble-files` originals untouched (tested against copies).
