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

## Merge-gate checklist (per change, before `--no-ff` to main)

1. Full test suite green (FRG-PROC-007).
2. `tools/trace.py` exit 0 — every implemented requirement has a tagged test
   (FRG-PROC-004/005).
3. `tools/soup_check.py` exit 0 — SOUP register matches the dependency manifests
   (FRG-PROC-012); any dependency add/remove/upgrade updated
   `docs/security/soup-register.md` in this change.
4. Manual sync verified (FRG-PROC-011): the change's declared manual impact
   (a required section of every proposal — sections touched, or "none" with
   rationale) was carried out in `docs/manual/` / `README.md`.
5. Security docs updated if the change added attack surface (FRG-PROC-006).
6. Code review + simplify pass on the branch diff.
7. Registry rows flipped, matrix regenerated, change archived, branch deleted
   after merge.
8. Release tag (FRG-PROC-013, from change 7 / v0.1.0 onward): annotated SemVer
   tag on the merge commit — milestone sets MINOR, change-within-milestone
   increments PATCH; message names the change id + FRG refs; tag and `main`
   pushed to `origin` in the same gate. Tags are immutable once pushed.

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
