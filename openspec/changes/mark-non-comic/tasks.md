# mark-non-comic — tasks

- [ ] 1.1 Migration 0033 classified_via (nullable Text) + model field
- [ ] 1.2 Sync write-back gate: skip operator-classified rows; publisher
      rules likewise (same gate)
- [ ] 1.3 Actions: single POST /entitlements/{id}/classify + bulk
      mark_non_comic / mark_comic (per-row outcomes; matched/ignored
      refused per row); resource exposes classified_via
- [ ] 1.4 Backend tests (FRG-SRC-016/012/004): stickiness across sync +
      rule change, both directions, bulk mixed outcomes, refusals
- [ ] 1.5 UI: bulk-bar marks, non-comic toggle hidden count, Mark-comic
      in the non-comic view, row action; vitest w/ FRG ids
- [ ] 1.6 Manual sources section; suites green; tools 0; e2e green;
      registry FRG-SRC-016; live-rig verification on the real bundle
