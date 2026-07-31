# review-selection-fixes — design

**Bulk restore defers, single restore does not.** FRG-SRC-004 already
sanctions an un-proposed restore (the budget-wall path leaves the
proposal NULL for the enrichment pass, and FRG-META-016 calls that
deferral, not failure). A bulk restore over N rows costs N × the CV
spacing — a minute for thirty rows — while committing as it goes, so the
operator sees a partial result on any refresh. Deferring makes the action
instant and the outcome whole. The single-row restore keeps its inline
recompute: it is one call, and the operator is watching that row.

**Non-comic as a scope, not a reveal.** The toggle's semantics ("stop
excluding") are what let a select-all span classifications, which is what
made per-row refusals read as partial failure. As a filter it composes
with select-all safely and gets an honest count.

**Settle before reporting.** Bulk invalidation is currently
fire-and-forget, so the result banner can render against a stale list.
Awaiting the refetch before reporting makes "12 restored, 18 refused"
agree with what is on screen.
