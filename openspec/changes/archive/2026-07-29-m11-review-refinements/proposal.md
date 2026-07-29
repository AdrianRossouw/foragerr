# m11-review-refinements — the review + search surfaces at real scale

## Why

Three friction points the owner hit dogfooding the shipped M11 review and
search surfaces (2026-07-28), all about acting on a *group* or an
*all-rejected* result rather than one row at a time:

1. Review rows collapse by `group_key` (change 2), but the only
   search/match affordance is per-row — matching a 145-row group means
   145 identical picks. The group header should let you match/search the
   whole group at once.
2. When you search-pick the correct series for one row, its same-group
   siblings keep their stale proposals. The change-1 sibling sweep only
   fires on the *add* path and only for siblings that already proposed
   that exact CV volume — a plain match-to-existing sweeps nothing.
3. The "Absolute Green Lantern" case: an interactive search returns
   releases but every one is rejected by the decision rules, so the UI
   offers no grab at all — even though the operator knows they want it.
   Worse, the server has **no approval gate on grab**: every decision,
   approved or rejected, is cached and grabbable by `(indexerId, guid)`;
   only the frontend hiding the button prevents it. That is a latent
   hole, not a safety property.

## What Changes

- **Grab is gated on approval, with an explicit force override**
  (MODIFIED `FRG-API-008` — complete restatement; migration `0030`):
  the interactive-search cache records each decision's approved state
  alongside its grab hand-off. `POST /release` grabs an approved release
  as today; a **rejected** release is refused with a typed 409 naming
  the constraint **unless** the request carries `force: true`, in which
  case the grab proceeds and is audit-stamped
  `triggered_by="interactive-forced"`. This closes the silently-grabbable
  gap and gives the all-rejected case a deliberate, recorded path.
- **Force-grab affordance** (new `FRG-UI-044`): rejected and
  temporarily-rejected releases render a "Grab anyway" action behind a
  confirm step (it bypasses the quality rules), sending `force: true`
  through the existing grab path. Approved rows are unchanged.
- **Group-key sibling proposal sweep on any operator pick** (new
  `FRG-SRC-014`): after an operator matches or adds a series for a review
  row — match-to-existing as well as add — the system sweeps the acting
  entitlement's same-`group_key` siblings (scoped to that `source_id`)
  and rewrites their proposals to that series. It writes **proposals
  only** (`review_status` stays `new`, never auto-committed), excludes
  already-`matched`/`ignored` rows, and is the operator's convenience,
  never a licence to accept unreviewed. Also exposes a bulk
  apply-to-group so a group-header pick fans one decision across the
  group in one action.
- **Group-header search/match affordance** (new `FRG-UI-043`): the
  collapsed group header offers a search/match picker seeded with the
  group's title; picking an in-library candidate bulk-matches the whole
  group, and picking a not-yet-added candidate adds it once and
  match-proposes the rest via the FRG-SRC-014 sweep for a single bulk
  accept.

## Capabilities

### New Capabilities

None — extensions of existing areas.

### Modified Capabilities

- `api`: MODIFIED FRG-API-008 (grab gated on approved-or-force, forced
  grabs audit-stamped; complete restatement).
- `sources`: ADDED FRG-SRC-014 (group-key sibling proposal sweep on any
  operator pick + bulk apply-to-group).
- `ui`: ADDED FRG-UI-043 (group-header search/match affordance), ADDED
  FRG-UI-044 (force-grab affordance).

## Impact

- Backend: search_ops/cache.py + a cache-table `approved` column
  (migration 0030) so grab can see the decision verdict; api/release.py
  (`grab_release` approved-or-force gate, `force` on ReleaseGrabRequest,
  forced audit stamp); sources/review.py (a `group_key`-scoped,
  source-scoped sibling-proposal sweep called from `match_entitlement`
  as well as the existing add/degrade tail; a bulk apply-to-group action
  on the existing bulk endpoint).
- Frontend: InteractiveSearchOverlay (Grab-anyway on rejected rows +
  confirm), EntitlementGroupHeader (search/match affordance), the group
  pick orchestration (bulk match vs add+sweep+accept).
- No dependency changes; no new listener/egress/parser of untrusted
  input. Migration 0030 is additive.
- **Security (FRG-PROC-006)**: force-grab deliberately bypasses the
  quality/decision rules, so it is an operator-authenticated,
  confirm-gated, audit-stamped action, and the change *adds* a
  server-side approval gate where none existed (a net tightening). The
  grab path takes no new untrusted input. Risk register: extend the
  grab/decision row noting the explicit force path and its audit trail;
  no new STRIDE category. Gate: medium tier + an adversarial angle on
  the force-grab gate and the group sweep at scale.
- Manual impact (FRG-PROC-011): `docs/manual/user/` search page
  (Grab anyway) and sources/review page (group-header match, sibling
  sweep behavior).

## Non-goals

- No auto-commit of swept siblings (proposals only — the change-1
  posture stands).
- No removal of the quality rules or a persistent "always allow this
  release" rule — force is per-grab and explicit.
- No stored `group_key` column: the sweep computes the key in Python
  scoped to one `source_id` (the change-1 design's recorded
  source-scoping follow-up); a stored/indexed column stays a future
  option if scale demands it.
- No change to how decisions are classified (approved vs rejected).

## Approval

Proposed under the M11 standing grant (owner approval 2026-07-27,
recorded in the m11-import-intelligence pre-design). All three
refinements are owner-requested from the 2026-07-28 dogfood. Force-grab
bypasses the quality rules by design — it is operator-initiated,
confirm-gated, and audit-stamped, and the change tightens the server
(adds the missing approval gate) rather than loosening it; called out
here for the owner's hard-stop review at milestone close rather than
assumed silently. The sibling sweep writes proposals only, never an
auto-commit.
