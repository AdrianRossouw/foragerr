# foragerr Commit Standard

Governed by **FRG-PROC-001** and **FRG-PROC-002** (message format) and
**FRG-PROC-007** (branching). Enforced by `.githooks/commit-msg` and
`.githooks/pre-commit` (installed via `git config core.hooksPath .githooks`).

## Branching and merge policy (FRG-PROC-007)

- Never commit directly on `main` — the pre-commit hook rejects it.
- Branch names: `change/<openspec-change-id>` for spec'd work,
  `research/<topic>` for research artifacts, `process/<name>` for governance.
- Land on `main` only via `git merge --no-ff <branch>` (preserves each commit's
  `Refs:` trailer in history), only while the full test suite passes, and delete
  the branch afterwards.
- Concurrent file-mutating agents each get their own worktree + branch
  (FRG-PROC-008); the orchestrator performs all merges.

## Format

```
<type>(<scope>): <subject>          # Conventional Commits, subject ≤ 72 chars

<body — what changed and why>

Refs: FRG-<AREA>-<NNN>[, FRG-<AREA>-<NNN>...]
```

- **type**: `feat` | `fix` | `refactor` | `perf` | `test` | `docs` | `spec` | `chore` | `build` | `ci`
- **scope**: optional, lowercase kebab-case module name (e.g. `import`, `opds`, `indexer`)
- **Refs trailer**: mandatory. Lists every requirement ID this commit implements, tests,
  or documents. Every ID must exist in
  [`docs/traceability/requirements-registry.md`](../traceability/requirements-registry.md).
- Merge and revert commits are exempt from the check.

## Requirement ID scheme

`FRG-<AREA>-<NNN>` — stable for the life of the project, never reused, never renumbered.
IDs are allocated in the requirements registry at the moment a requirement is first
written into an OpenSpec change proposal.

| AREA | Domain |
|------|--------|
| PROC | Development process and governance |
| SEC  | Security requirements (from threat analysis) |
| NFR  | Other non-functional requirements |
| SER  | Series/library management |
| META | Metadata (ComicVine) |
| IDX  | Indexers (Newznab: DogNZB, NZB.su; later torrents) |
| DL   | Download clients (SABnzbd; later qBittorrent) |
| DDL  | Built-in direct-download engine |
| IMP  | Import, filename parsing, renaming |
| QUAL | Format & quality profiles |
| SRCH | Search & wanted scheduling |
| PP   | Post-processing (import execution, tagging, dupes) |
| PULL | Weekly pull / release calendar |
| ARC  | Story arcs |
| TOR  | Torrents (deferred) |
| NOTIF| Notifications |
| SCHED| Scheduling & queues |
| OPDS | OPDS server |
| UI   | Web frontend |
| API  | Backend HTTP API |
| DB   | Persistence |
| DEP  | Packaging and deployment |
| AUTH | Authentication (deferred milestone) |

## Examples

```
feat(import): parse volume designators in comic filenames

Handles 'v2'/'Vol. 2'/'Volume Two' variants per the parsing spec,
matching Mylar3 behavior for the regression corpus.

Refs: FRG-IMP-003, FRG-IMP-004
```

```
spec(opds): propose OPDS acquisition feed capability

Refs: FRG-PROC-003
```
