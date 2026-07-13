# logout-failure-handling

## Why

Dogfooding (2026-07-13) surfaced that the logout control navigates to the login screen and clears the client's auth state on `onSettled` — **regardless of whether the server actually terminated the session**. When the logout POST fails (a 4xx/5xx, or a network error), the operator is shown the login screen while their session cookie is still valid: a reload or back-navigation silently re-authenticates them. On a shared or kiosk browser this is a real exposure — "log out" that leaves the session grabbable. The session cookie is HttpOnly, so the client cannot clear it itself; only a confirmed server-side logout truly ends the session, and the UI must not claim success without it.

## What Changes

- **The logout control signals success only on a confirmed server-side logout.** On the logout request succeeding (HTTP 204), the client clears local auth state and navigates to the login screen as today. On failure it does **not** clear auth state or navigate — the session is (or may still be) alive — and instead surfaces an accessible, retryable error, leaving the operator authenticated so they can try again.
- No backend change: `POST /api/v1/auth/logout` already deletes the session server-side and 204s (FRG-AUTH-004). This closes the client-side gap where a failed logout was reported as a successful one.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `auth`: FRG-AUTH-004 (session management) — add the client-side logout-confirmation behavior: the UI SHALL treat logout as complete only when the server confirms session termination, and SHALL surface a retryable failure otherwise.

## Impact

- **Code**: `frontend/src/components/LogoutButton.tsx` (success/failure split), a small accessible error surface in the header actions region.
- **Tests**: vitest tagged FRG-AUTH-004 — success clears+navigates; a failed logout neither clears auth state nor navigates and shows a retryable error.
- **Dependencies / SOUP / security docs / registry**: none new (FRG-AUTH-004 already registered; a scenario is added to the existing requirement). No new attack surface — this removes a client-side false-success.
- **Manual** (FRG-PROC-011): `docs/manual/user/` auth/login section note that a failed logout keeps you signed in and asks you to retry (small; sections touched listed in tasks).

## Approval

Approved — Adrian, 2026-07-13 (in-session: "the logout defect should be fixed").
