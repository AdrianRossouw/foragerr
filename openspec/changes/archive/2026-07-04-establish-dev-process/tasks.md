# Tasks

## 1. Governance artifacts

- [x] 1.1 Write `dev-process` spec with FRG-PROC-001..006
- [x] 1.2 Create requirements registry with the six PROC rows (`active`)
- [x] 1.3 Document commit standard in `docs/process/commit-standard.md`

## 2. Enforcement

- [x] 2.1 Implement `.githooks/commit-msg` (Conventional Commits + Refs trailer + registry check)
- [x] 2.2 Set `git config core.hooksPath .githooks`
- [x] 2.3 Verify the hook rejects a non-compliant message and accepts a compliant one

## 3. Orientation

- [x] 3.1 Write project `CLAUDE.md` encoding the process for all agents
- [x] 3.2 Initialize OpenSpec structure and Claude skills (`openspec init --tools claude`)
