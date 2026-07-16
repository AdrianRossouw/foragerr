# m9-cv-key-live-reload — tasks

## 1. Live key application (FRG-META-018)

- [x] 1.1 `config_resources._apply`: after swapping `app.state.settings`, refresh `app.state.commands.context.settings` (guarded — bare test apps may lack the service)
- [x] 1.2 Test (FRG-META-018, pytest): save a key via `PUT /api/v1/config/general` against a running app; assert the command service context now carries the new key (and a second save updates it again)

## 2. Health truthfulness (FRG-META-019)

- [x] 2.1 `metadata/ratelimit.py`: add auth-failure state to the gate (set/clear + surfaced in `comicvine_health()` as `auth_failed`)
- [x] 2.2 `metadata/comicvine.py`: `_raise_for_status` sets the state on 401/403; a 200 response clears it
- [x] 2.3 `health/service.py::_comicvine_component`: auth-failed reports error state naming the credential cause, remediation → Settings → General (checked before the rate-limit/budget dimensions)
- [x] 2.4 Test (FRG-META-019, pytest): 401 response → health component error w/ Settings remediation; subsequent 200 → OK

## 3. Failure cause in the UI (FRG-UI-030)

- [x] 3.1 `api/hooks.ts` `useWatchedCommand`: expose `failureReason` (resource `error` when status is terminal `failed`)
- [x] 3.2 `SeriesDetail` command chip: render reason with failed status (truncated, full text in `title`); reason-less failures unchanged
- [x] 3.3 Test (FRG-UI-030, vitest): failed command w/ error renders reason; failure without error renders bare status

## 4. Docs, gate, merge

- [x] 4.1 Manual (FRG-PROC-011): `docs/manual/admin/configuration.md` "Setting the ComicVine key" — note the key applies to background workers immediately too; Health section gains the auth-failed state row
- [ ] 4.2 Suites green (pytest + vitest + tsc); regenerate traceability matrix; soup_check + risk-register check exit 0 (no dep changes; no new attack surface)
- [ ] 4.3 Tiered review gate (small: 2-3 angles + Codex); merge --no-ff; /release v0.9.11; delete branch
