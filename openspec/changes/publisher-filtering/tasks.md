# publisher-filtering — tasks

## 1. Library-wide rules + defaults (FRG-SRC-012)

- [ ] 1.1 `DEFAULT_NON_COMIC_PUBLISHERS` constant (shape + `*`-substring
      semantics mirroring `DEFAULT_IGNORED_PUBLISHERS`); one source of truth
- [ ] 1.2 Library-wide config value seeded from it (fresh install only);
      `sources/classify.py` reads the library-wide list, not per-source
- [ ] 1.3 Config resource (get/set) for the list, replacing the per-source
      publisher-rules PATCH on `api/sources.py`
- [ ] 1.4 Migration: union existing per-source `publisher_rules` into the
      library-wide value (deduped, decrypt-failure contributes nothing)
- [ ] 1.5 Tests: defaults present on fresh install + removable; existing
      config kept; reclassify `new` across sources; matched/ignored
      untouched; per-source rules migrate in

## 2. Settings panel, plain language (FRG-UI-046)

- [ ] 2.1 Remove `PublisherRules` from `StoreManage`; add a
      publisher-filtering panel to Settings beside the CV ignore list
- [ ] 2.2 Plain copy (RPG / tech-book / art-book examples; no "escape
      hatch," no single-genre framing); next-sync + sticky-decision note
- [ ] 2.3 Tests (vitest): panel in Settings shows defaults + add/remove;
      no publisher-rules control on the Sources screen; copy assertion

## 3. Docs + verification

- [ ] 3.1 `docs/manual/` settings page (the list + what the defaults do)
      and sources page (the control moved); README labelling if needed
- [ ] 3.2 Full backend (xdist) + frontend (serialized) green; soup 0; e2e
      green; trace picks up FRG-UI-046 + the FRG-SRC-012 restatement
