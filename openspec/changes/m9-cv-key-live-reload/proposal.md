# m9-cv-key-live-reload

## Approval

**DRAFT — pending owner approval (FRG-PROC-009).** Registry IDs not yet allocated;
allocate in `docs/traceability/requirements-registry.md` at approval.

## Why

A ComicVine key saved through Settings → General works immediately for the
request-path lookup (Add New search) but never reaches worker-context clients:
the very first series a fresh install adds fails its refresh with
`ComicVineAuthError (HTTP 401)` and lands as a 0-issue shell showing only
"Refresh: failed", while System → Health reports ComicVine **OK**. The only
remedy is a container restart, which nothing suggests. This is the
long-standing first-run killer, reproduced and root-caused during the M9
simulated-user run (finding F1, `docs/research/m9-user-sim-findings.md`): the
worker CV client is constructed with the boot-time key snapshot and is never
rebuilt after a config save.

## What Changes

1. **Live key resolution.** Worker-context ComicVine clients resolve the API
   key at request time from current settings (or are rebuilt on config-save
   events), so a key saved in the UI applies to refreshes, imports, and credit
   jobs without restart — matching the documented "applies immediately, no
   restart needed" behavior that today is only true for the lookup path.
2. **Truthful health.** A worker-side ComicVine auth failure marks the
   ComicVine health component non-OK with an actionable message (key missing /
   invalid — check Settings → General), instead of Health contradicting the
   failure.
3. **Refresh failure surfaced.** A failed `refresh-series` shows its cause on
   the series page (e.g. "ComicVine rejected the API key"), not a bare
   "Refresh: failed" whose explanation lives in a log traceback.

## Impact

- Requirements (allocate at approval): one CONF/META requirement for live key
  application across execution contexts; one HLTH/UI requirement for
  worker-auth-failure health truthfulness; one UI requirement for surfaced
  refresh-failure cause.
- Code: `metadata/comicvine.py` client construction / settings access,
  worker context wiring, health component, series-detail refresh status.
- Tests: worker-context key-change test (set key after boot → refresh
  succeeds without restart); health reflects 401; UI shows cause.
- Manual: `docs/manual/admin/configuration.md` "Setting the ComicVine key"
  already promises immediate application — behavior catches up to the doc;
  add a line covering worker contexts. Security docs: no new surface.
- SOUP: none.
