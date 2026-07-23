# pull-backfill-window — tasks

## 1. Implementation (FRG-PULL-010)

- [ ] 1.1 `config.py`: `pull_backfill_weeks` (int, default 4, ge=0; clamp >12
      at use with a log line); `configuration.md` row
- [ ] 1.2 `pull/commands.py`: widen `_fetch_weeks` when `repo` reports an
      empty store; entries ride the existing derived-week store/match path
- [ ] 1.3 Tests: empty-store widening, non-empty no-widening, 0-disable,
      >12 clamp; all tagged FRG-PULL-010

## 2. Gate and release

- [ ] 2.1 Registry row → implemented; matrix regen; trace/soup/risk green
- [ ] 2.2 Full suite; small review tier + Codex; CHANGELOG + bump; merge,
      tag, release
