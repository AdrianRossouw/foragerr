# calendar-discovery-default

## Why

Owner decision (Adrian, 2026-07-11): "calendar should show all releases
first, because it also acts as discovery for new things to follow (closer
to how Mylar uses the pull list versus Sonarr uses the calendar)." The
shipped Following default came from the design handoff §4 and quietly
contradicted the owner's standing 2026-07-05 domain direction that
discovery of unfollowed books is the point of the pull list.

## What Changes

- **Calendar scope defaults to All releases** (FRG-UI-018 amended); the
  Following scope stays one click away on the same segmented control, and
  all other calendar behavior (week nav, publisher filter, banner
  wording per scope, new-series strip) is unchanged.
- Manual Calendar paragraph reworded (defaults to the full week's
  releases; Following narrows it). decisions.md entry recorded.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `ui`: FRG-UI-018 amended (default scope All releases; discovery-first
  rationale).

## Non-goals

- No persisted scope preference (component state per visit; revisit only
  if asked).
- No other calendar changes.

## Impact

- **Frontend**: one default flip in `CalendarScreen.tsx` + test updates
  (default-load scenario asserts All; scope-toggle test direction flips).
- **Docs**: manual §Calendar, decisions.md, spec baseline sync.
- **Backend/security/SOUP**: none.

## Approval

Direct owner instruction, Adrian 2026-07-11 (recorded in decisions.md).
Small-tier gate.
