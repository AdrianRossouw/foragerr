# m9-ux-diagnosability

## Approval

**Approved by Adrian, 2026-07-16 (in session, FRG-PROC-009)** as part of the
M9-remainder plan (third of three M9-tail changes, → v0.9.13). Registry IDs
allocated at implementation kickoff. Scope notes from approval:

- Item 8 (read-only roots, F14) was not explicitly decided; resolved by
  default to the conservative option — **document** the writability
  requirement in the manual, no behavior change — unless the owner redirects
  before implementation.
- A states audit (empty/loading/error coverage per screen) runs before
  implementation; any real findings fold into this change's scope.
- **Gate amendment (owner, 2026-07-16):** item 6's file-less-series hiding is
  **opt-in, not default** — the OPDS shelf mirrors the full library (wanted
  series included) out of the box; `opds_hide_fileless_series=true` enables
  the reading-only shelf. HEAD support unchanged.
- The handoff fidelity audit is **dropped** (owner: the handoff was a quick
  sketch; fidelity is not maintained). An accessibility scan is deferred to
  after the M9 release cycle, with axe-tooling-in-gates evaluated separately.

## Why

The M9 simulated-user run (findings F2–F4, F11, F14, F16, F19, F22, F23 in
`docs/research/m9-user-sim-findings.md`) surfaced a consistent pattern: the app
usually *knows* what's wrong or what the user should do next, but says it as
inert text, hides it on another screen, or omits it — costing clicks (root
folder detour: ~11 actions vs ~6), false conclusions (empty Calendar during a
pull-source outage reads as "nothing ships this week"), and reader-client
breakage (OPDS HEAD 404). M9 is the experience-refinement milestone; this
change is the catch-all for those seams.

## What Changes

1. **Actionable guidance links.** Error/guidance strings that name a settings
   destination become links: ComicVine-key error → Settings → General;
   add-dialog root-folder notice → Media Management (until 2. lands).
2. **Inline root-folder creation in the add dialog.** First-run add flow
   offers a root-folder input inline (Sonarr pattern), removing the
   leave-and-return detour; series search/dialog state survives.
3. **Calendar degraded-source notice.** When pull-source health is degraded,
   the Calendar shows an inline notice ("weekly source unavailable — showing
   your library's data only") instead of a bare zero-count line.
4. **Unknown routes render NotFound.** Any unmatched SPA route shows the app
   shell + a not-found screen with a link home, never a blank page.
5. **UI-facing copy scrub.** Health warnings speak UI language ("Settings →
   General", not `pull_source_url`); config-key names remain in logs/docs.
6. **OPDS reader compatibility.** HEAD allowed on OPDS feed/file/page routes;
   file-less series omitted from OPDS shelves (config-gated, default on).
7. **Operator log parity.** Library-import per-group failures log at WARNING
   with reasons; queue shows a "completed — awaiting import" state so fast
   grabs don't render an empty Queue between SAB completion and the next
   track-downloads tick.
8. **Read-only root decision (owner input).** Either support read-only roots
   for in-place-only libraries (refuse only operations that need writes) or
   keep the writability requirement and document it in the manual — decide at
   approval; the run hit the refusal with a read-only mount (F14).

## Non-goals

- No first-run wizard (standing owner decision, M8).
- Import-review card/picker overhauls live in `m9-import-heuristics`.

## Impact

- Requirements: ~5–6 new UI/OPDS/NFR requirements (allocate at approval).
- Code: frontend (links, dialog, calendar, router fallback, queue state),
  OPDS router (HEAD, shelf filter), log levels; no schema changes expected.
- Tests: route-fallback render, calendar degraded render, OPDS HEAD contract
  + shelf filtering, linkified errors; e2e negative-path additions
  (unconfigured states already covered — extend to degraded pull source).
- Manual: `docs/manual/user/web-ui.md` (calendar notice, queue states),
  `docs/manual/user/reading-opds.md` (HEAD, empty-shelf behavior),
  `docs/manual/admin/configuration.md` (read-only-root decision).
- Security: HEAD on OPDS is same auth perimeter (Basic) — no new surface;
  note in STRIDE only if the router gains a distinct handler. SOUP: none.
