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
   **Living-register discipline** (living-docs review, 2026-07-13): status-bearing
   documents — the risk register, SOUP register, requirements registry — are
   updated by **replacing** the row's current-state content, never by appending
   dated narrations. A row answers "what is true now"; history is git's job
   (`git log --follow` on the document).
6. Code review + simplify pass on the branch diff, including an
   independent-model (Codex) full-diff review as a required independent
   perspective (owner instruction 2026-07-10). The review fleet is
   **tiered to the diff** (owner instruction 2026-07-10, m4-logs-viewer):
   - **Small** (≲500 changed lines AND no new attack surface): 2–3
     targeted angles + Codex; mechanical angles (test/trace audit, token
     discipline) run on the cheaper model tier.
   - **Medium**: 4–5 angles + Codex, mixed model tiers.
   - **Large or security-touching** (new listener/endpoint, parser of
     untrusted input, credentials — regardless of size): the full
     eight-angle fleet + Codex, subtle angles on the strong model tier.
     A size-small change that adds attack surface keeps the small fleet
     but MUST include a dedicated adversarial security angle for that
     surface, and the new surface's spec MUST carry a tested
     abuse/leak scenario.
   Angle count and tier are recorded in the gate evidence.
7. History hygiene (FRG-PROC-015, public repository): the full-history secret
   scan recorded in `docs/security/history-scan.md` must name an
   ancestor-or-equal of the merge HEAD; re-run and append to its re-scan log
   before any history-affecting operation (force-push, rewrite) is pushed to
   the public remote. Run the scan with the repo's `.gitleaks.toml`
   (`gitleaks git --config .gitleaks.toml`), whose custom `bare-key-hex` rule
   closes the KA-001 detection gap and whose fixture allowlist keeps the
   synthetic `backend/tests/**` secrets from re-flagging under that rule.
8. Registry rows flipped, matrix regenerated, change archived, branch deleted
   after merge.
9. Release record per FRG-PROC-013 (`openspec/specs/dev-process/spec.md` owns the
   scheme), from change 7 / v0.1.0 onward:
   - **Pre-merge** (in the change itself): the release version's `CHANGELOG.md`
     entry (Added/Changed/Fixed/Security + FRG refs + upgrade notes) is written, and
     `backend/pyproject.toml` `version` is set to the release version.
   - **Post-merge** (immediately after the merge commit exists — the one post-merge
     step): create and push the annotated SemVer tag, then publish a GitHub Release
     (`gh release create`) for it carrying that CHANGELOG entry as its body.

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
| CRTR | Creators & follows (M5) |
| SRC  | Store sources & entitlements (M6: Humble Bundle first) |
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
