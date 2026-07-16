# dev-process — m9-a11y-fixes deltas

## ADDED Requirements

### Requirement: FRG-PROC-019 — Accessibility scan in the e2e gate

The e2e harness SHALL include an accessibility tier: an axe-core WCAG 2.1 A/AA scan of the authenticated core screens that fails the suite on any serious- or critical-impact violation, so accessibility conformance (FRG-UI-038) is enforced wherever the e2e gate runs rather than depending on one-off audits.

- **Milestone**: M9 (m9-a11y-fixes)
- **Source**: Owner direction 2026-07-16 ("the tooling might be worth pulling in to the release cycle").
- **Notes**: Zero-tolerance with no baseline file — the fixes land in the same change, so the clean state is the starting invariant. axe-core is e2e dev tooling (SOUP-register-exempt per the harness's existing note, like Playwright).

#### Scenario: A regression fails the harness

- **WHEN** a change reintroduces a serious-impact WCAG violation on a scanned screen and the e2e suite runs
- **THEN** the a11y spec fails naming the rule and the offending nodes, and the run exits non-zero
