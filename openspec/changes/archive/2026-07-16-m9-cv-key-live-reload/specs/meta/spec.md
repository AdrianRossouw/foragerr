# meta — m9-cv-key-live-reload deltas

## ADDED Requirements

### Requirement: FRG-META-018 — Runtime credential application across execution contexts

The system SHALL apply a ComicVine API key saved at runtime (Settings → General / `PUT /api/v1/config/general`) to all subsequent ComicVine requests in every execution context — request handlers, command workers, and scheduled tasks — without a process restart. The environment-variable precedence rule is unchanged: when `FORAGERR_COMICVINE_API_KEY` is set, the UI field is read-only and no runtime save occurs.

- **Milestone**: M9 (m9-cv-key-live-reload)
- **Source**: M9 simulated-user finding F1 (`docs/research/m9-user-sim-findings.md`) — the first-run killer: a UI-saved key worked for request-path lookups but never reached worker-context clients until restart, failing every fresh install's first series refresh with `ComicVineAuthError` while the docs promised "applies immediately, no restart needed".
- **Notes**: Root cause was a boot-time `Settings` snapshot in the command service's `HandlerContext`; the config-save path swaps `app.state.settings` but nothing refreshed the worker context. The fix keeps one write point (`_apply`) refreshing both. Worker *pool sizes* remain boot-time (documented restart-required) — only the settings object handlers read per-run is live.

#### Scenario: Key saved in the UI reaches the next worker-context refresh without restart

- **WHEN** no ComicVine key is configured, the operator saves a key via Settings → General, and a `refresh-series` command then runs in a command worker
- **THEN** the refresh's ComicVine requests carry the newly saved key and the refresh succeeds, with no process restart between the save and the run

#### Scenario: Subsequent config saves keep workers current

- **WHEN** an already-running deployment saves a *changed* ComicVine key via the same endpoint
- **THEN** the next command-worker ComicVine request uses the changed key, and the previous key is not sent again by any execution context

### Requirement: FRG-META-019 — ComicVine authentication-failure health truthfulness

WHEN a ComicVine request fails authentication (HTTP 401/403 — missing or invalid key), the system SHALL set the ComicVine health component to an error state whose message names the credential cause and whose remediation directs the operator to Settings → General, regardless of which execution context issued the request; the state SHALL clear automatically on the next successful ComicVine request. The auth-failure dimension is independent of the rate-limit back-off and per-path budget dimensions.

- **Milestone**: M9 (m9-cv-key-live-reload)
- **Source**: M9 simulated-user finding F1 — during the reproduced first-run failure, System → Health reported ComicVine **OK** while every worker request was rejected 401; the only diagnosis was a traceback in Logs.
- **Notes**: Mirrors the existing degraded-flag mechanics in `metadata/ratelimit.py` (module-level gate state read by `health/service.py::_comicvine_component`). Set at the single `_raise_for_status` choke point, cleared at the single success point, so no per-caller wiring.

#### Scenario: Worker-context auth failure surfaces on Health

- **WHEN** a command-worker ComicVine request is rejected with HTTP 401
- **THEN** the ComicVine component on System → Health reports an error state naming the authentication/key cause with remediation pointing at Settings → General

#### Scenario: Recovery clears the state without restart

- **WHEN** the auth-failure state is set and a later ComicVine request (any context) succeeds
- **THEN** the ComicVine component returns to OK with no operator action beyond fixing the key
