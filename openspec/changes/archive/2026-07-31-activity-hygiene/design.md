# activity-hygiene — design

## Context

The queue's layout predates the shared data-table styles: it duplicates
them locally, wraps nothing, and has no scroll container, so unbreakable
release tokens push the actions column off-frame and the whole page
scrolls sideways. The screen is also frozen at page 1 of 20 with no
paging component, and the only cleanup is one dialog per row. Failed
rows render 0-byte progress bars. The single-remove path (409 while
importing; optional blocklist via the shared key; best-effort client
removal) is correct and complete — it just has no bulk form.

## Decisions

**D1 — Bulk remove is a server endpoint, not a client loop.** One
request, per-row outcomes, the sources bulk endpoints' established
result shape. A client-side DELETE loop would lose atomicity of
reporting and hammer the API for large clears.

**D2 — Clear failed is selection sugar over the same bulk remove.**
It pre-selects failed rows and opens the same dialog (blocklist choice
included) — no second removal semantics, no hidden defaults.

**D3 — Failed rows keep their columns, lose their noise.** Status chip
and reason popover carry the failure; progress/bytes render only for
rows that are actually moving. Rows titled by opaque tokens are
identified by their series/issue columns — no attempt to prettify
release names.

**D4 — Adopt the shared table styles rather than patch the local copy.**
`dataTable.module.css` + a tableWrap scroll container is what History/
Wanted/Blocklist already do; the queue's local duplicates retire.

## Risks / Trade-offs

- [Bulk remove of many rows does N best-effort client calls] → bounded
  by page selection; failures are per-row and never block de-tracking.
- [Clear failed with blocklist chosen blocks releases the user may want
  again] → the dialog makes it an explicit choice, same as single
  remove.

## Migration Plan

None — no schema change; frontend + one additive endpoint. Rollback =
revert.

## Open Questions

None. Tracked-download retention (failed rows aging out automatically)
is deliberately out of scope, recorded as a follow-up idea.
