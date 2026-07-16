# m9-a11y-fixes

## Approval

**Approved by Adrian, 2026-07-16 (in session, FRG-PROC-009):** "can you
approve it pls" — the a11y fixes plus axe tooling pulled into the release
cycle, as recommended after the post-cycle scan. The remaining M9-adjacent
items (Cross Cult default sanity-check, M11 slotting, Panels test) are
deferred to future sessions by the same message. Registry IDs FRG-UI-038,
FRG-PROC-019.

## Why

The owner-directed post-cycle accessibility scan (axe-core 4.12, WCAG 2.1 AA
ruleset, all 21 screens of v0.9.13) found four serious-impact issues — small,
but every one lives in a shared component so every screen inherits them:

1. The header connection dot is a `span` carrying `aria-label` with no role —
   prohibited ARIA, and the connection state is invisible to a screen reader.
2. Sidebar group labels and footer text render #7a7a7a on #262626 — 3.52:1
   contrast against the 4.5:1 minimum.
3. Indexer/download-client provider cards are `div role="button" tabindex=0`
   wrapping a focusable enable toggle — nested interactive controls, broken
   keyboard interaction order.
4. The System → Health components table scrolls without keyboard access.

The owner also asked whether the scan tooling is "worth pulling in to the
release cycle" — it is: axe-core rides the existing e2e harness for the cost
of one dev dependency and one spec, turning today's clean state into a gate
invariant instead of a one-off audit.

## What Changes

1. Fix all four findings (semantics/contrast only — no behavior change).
2. `e2e`: axe-core dev dependency + an a11y spec that injects axe on the
   authenticated core screens and fails on any serious/critical WCAG 2.1 AA
   violation — zero-tolerance, no baseline file, because after (1) the count
   is zero (FRG-PROC-019).
3. Requirement FRG-UI-038 pins the conformance; unit-level tagged tests cover
   the four fixed components; the e2e spec carries both IDs.

## Impact

- Requirements: FRG-UI-038 (ui), FRG-PROC-019 (dev-process).
- Code: frontend shared components (AppShell/Sidebar CSS + connection dot,
  provider card, health table), e2e harness.
- Manual: none (no user-facing behavior change; visual semantics only) —
  rationale per FRG-PROC-011. e2e/README.md documents the a11y tier.
- SOUP: axe-core is e2e dev/test tooling, outside the SOUP register's
  declared scope (same precedent as Playwright — e2e/README.md SOUP note).
- Security: none (no new surface).
- Site: no site work — the registry rows, tagged tests, CHANGELOG entry, and
  archived change surface through the existing generated-facts pipeline.
