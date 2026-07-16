# m9-publisher-ignore-defaults

## Approval

**Approved by Adrian, 2026-07-16 (in session, FRG-PROC-009)** as part of the
M9-remainder plan (second of three M9-tail changes, → v0.9.12). Carved out of
the corpus-reduction discussion on `m9-import-heuristics` so the subscribe-flow
fix ships in M9 while the import milestone reuses the same list. Registry IDs
allocated at implementation kickoff.

## Why

ComicVine's series corpus is full of foreign-market reprints, and foragerr
currently ranks them naively: the #1 Add New result for "Ultimate Spider-Man"
is a German Panini volume; Marvel's 2024 ongoing sits 9th (M9 finding F17,
`docs/research/m9-user-sim-findings.md`). A trusting user subscribes to the
wrong volume of the biggest current book. Mylar solved this with a global
ignored-publishers filter applied to every CV volume-search result
(`ignored_publisher_check`, wildcard-capable) — foragerr inherited the setting
(`comicvine_ignored_publishers`) but ships it empty, config-file-only, and
hard-dropping. This change gives the list teeth (a shipped default), a face
(Settings UI), and a receipt (recoverable hiding).

## What Changes

1. **Curated default list for fresh installs.** New installs seed
   `comicvine_ignored_publishers` with a conservative list of unambiguous
   reprint-market publishers (wildcard-capable, e.g. `Panini*`, `Urban
   Comics`, `Planeta DeAgostini`, `Cross Cult`, `Editorial Televisa`,
   `Dolmen*`, `Yermo*`; exact list fixed at implementation). **Existing
   configs keep their stored value** — same upgrade semantics as the
   `pull_enabled` default flip (v0.5.1): the new default applies to fresh
   installs only; the manual documents how upgraders opt in. Publishers of
   originals (e.g. Les Humanoïdes Associés) stay off the default list.
2. **Settings → General exposure.** The list is editable in the UI (chips or
   comma text field), with the same env-var-wins/read-only indication as the
   ComicVine key.
3. **Hide, don't drop, in Add New.** Filtered results collapse behind an
   explicit count — "12 results hidden by your publisher ignore list — show" —
   restoring them for that search in one click, with a link to edit the list.
   (Mylar drops silently; the recoverable form is what makes a shipped
   default acceptable.)

## Non-goals

- No language/market *ranking* heuristics — that is milestone scope
  (import-intelligence), where the same list also filters import-proposal
  and cover-candidate sets.
- No per-series overrides.

## Impact

- Requirements: ~2–3 CONF/SRCH/UI requirements (allocate at kickoff);
  existing behavior of `comicvine_ignored_publishers` is MODIFIED — restate
  the complete scenario set (v0.6.3 lesson).
- Code: config defaults/first-run rendering, series-lookup filter path
  (already exists), Settings → General screen, Add New results UI.
- Tests: fresh-install default seeding; upgrade keeps stored value; wildcard
  matching; hidden-count render + show toggle; filter applies to lookup.
- Manual: `docs/manual/admin/configuration.md` (setting row + default +
  upgrade note), `docs/manual/user/search.md` (hidden results UI).
- Security: none (no new surface). SOUP: none.
