# Tasks: m2-manual-import

- [ ] Delta specs drafted (pp: PP-016/017, api: API-015, ui: UI-014,
      imp: IMP-024) + design.md — Opus drafter, grounded in importer/evidence.py,
      decisions.py, pipeline.py, security/archives.py
- [ ] Area 1 (backend): ComicInfo read (hardened XML, evidence layer) + manual
      candidate source + override execution + manual-import API — Opus worktree
- [ ] Area 2 (backend): ComicInfo write-on-import (safe cbz rewrite behind
      FRG-SEC-003) — Opus worktree, after area 1's comicinfo module lands
- [ ] Area 3 (frontend): manual-import overlay + path picker — Opus worktree
- [ ] Gate: 9-angle review + Codex, fixes, suites + e2e green, security docs
      (RISK-010/024 M2 dispositions, COMP 7 delta), manual sync, registry flip
      (5), trace/soup 0, archive, --no-ff merge, tag v0.2.1, push
