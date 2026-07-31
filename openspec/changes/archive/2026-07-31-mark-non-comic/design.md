# mark-non-comic — design

**Provenance column, not a boolean lock.** `classified_via` (nullable
Text: `operator` vs NULL/automatic) follows matched_via: it answers who
classified, lets the sync gate skip operator rows with one predicate,
and keeps a future automatic-provenance value possible without another
column. dedupe_opt_out's set-only precedent applies: an operator mark is
never cleared automatically; the reverse mark is another operator mark.

**Both directions are operator marks.** Mark-comic on a mis-marked row
stamps operator provenance too — returning a row to "automatic" is
deliberately not offered (a cleared row would flip back on the next
sync, making the un-mark a gesture; the house never-reverse rule).

**Only `new` rows are markable.** Matched/ignored rows refuse per-row
with the established restore-first message shape; classification is a
review-time decision, not a post-decision edit.

**Counts and visibility ride existing machinery.** `other`-classified
rows already hide behind the non-comic toggle; the change adds the
hidden count to the toggle label and the reverse mark inside that view.
The bulk endpoint reuses the applied/errors shape; the bulk bar reuses
BULK_VERBS.
