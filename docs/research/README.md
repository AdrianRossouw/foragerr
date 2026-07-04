# Reference Research

Behavioral documentation mined from read-only analysis of Mylar3 and Sonarr
(shallow clones in gitignored `.reference/`, cloned 2026-07-04). Produced by five
read-only research agents per FRG-PROC-008; key file:line claims were spot-checked
against the reference source by the orchestrator before these documents were
committed. These are inputs to the Phase 2 requirements baseline (FRG-PROC-003) and
the STRIDE threat analysis (FRG-PROC-006) — they describe behavior and never port code.

| Document | Covers |
|----------|--------|
| [mylar-filename-parsing.md](mylar-filename-parsing.md) | Full parser behavior catalogue, 67-filename regression corpus, known bugs, candidate requirements |
| [mylar-comicvine.md](mylar-comicvine.md) | ComicVine API usage, rate limiting, volume matching, sync; weaknesses |
| [mylar-ddl.md](mylar-ddl.md) | GetComics DDL provider: search ladder, link resolution, download worker, verification; security flags |
| [mylar-opds.md](mylar-opds.md) | OPDS 1.x + OPDS-PSE implementation, auth model, client quirks; security flags (path traversal, SQL concat) |
| [mylar-feature-surface.md](mylar-feature-surface.md) | Everything else: pull list, arcs, search scheduling, post-processing/tagging, providers, notifications, config; ends in the AREA-coded capability map |
| [sonarr-architecture.md](sonarr-architecture.md) | Domain model, indexer abstraction, decision engine, SABnzbd + queue tracking, import pipeline, eventing, API v3 shapes |

Security-relevant observations in these documents feed `docs/security/` in Phase 2.
