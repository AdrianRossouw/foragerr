# roadmap-reshape — design

## Context

Owner-approved reshaping (2026-07-10), same mechanism as 2026-07-05. Inputs:
the design-handoff review (pull screen presupposes the new shell; creators is
its own domain), the Humble-credentials analysis (store-account credentials
require at-rest encryption before the importer exists), and the owner's
torrents-before-auth preference with tracker-etiquette seeding controls.

## Decisions

1. **Pull experience builds once, in the new shell** — ch2 rescopes into M4
   as its capstone change rather than shipping twice.
2. **Torznab-only torrent indexing.** foragerr speaks one generic protocol;
   Prowlarr/Jackett own tracker connectivity, session auth, and CloudFlare
   battles. Rejected: native per-tracker implementations (Mylar's 32P-style
   session scraping) — per-tracker attack surface and maintenance for zero
   architectural gain, and indexer aggregators are the established *arr
   deployment pattern. Private-tracker etiquette lands client-side
   (per-torrent ratio/seed-time limits) plus per-indexer seed criteria.
3. **FRG-AUTH-008 decouples from app auth.** At-rest credential encryption is
   a data-protection control, not a login feature; it moves to M6 as the
   sources milestone's first change (env-only key per the recorded owner
   direction; existing provider keys migrate so there is one store).
4. **Milestone metadata moves in place; two carried deltas.** Most moves
   change only `Milestone:` bullets and registry cells (`tools/trace.py`
   enforces registry↔spec agreement); requirement text changes ride proper
   MODIFIED deltas — FRG-AUTH-008 (env-only key) and FRG-AUTH-001 (auth
   boundary M3→M8 in its normative sentence), plus FRG-PROC-011 (README
   sync footing).
5. **Grant boundary is explicit everywhere it matters**: the registry legend
   and the proposal both state that M8 auth needs fresh approval.

## Risks / Trade-offs

- [Auth slips ~4 milestones on a public codebase] → RISK-020 re-acceptance
  recorded with the owner's date; Tailscale-only posture and its manual
  controls unchanged; review trigger remains any exposure beyond the tailnet.
- [M4 UI rebuild destabilizes shipped screens] → M4 decomposition keeps
  changes screen-scoped with the e2e spine green at every gate; screenshot
  refresh tooling lands early in M4 so labelling keeps pace.

## Migration Plan

Docs-only. Rollback = revert.

## Open Questions

- None (Transmission-vs-qBittorrent requirement wording resolves in the M7
  proposal's delta).
