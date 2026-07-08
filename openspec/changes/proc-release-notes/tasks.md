Single-area change (repository-level release artifacts + one process spec + one
process doc). No product code, no worktree fan-out. FRG-PROC-013 is a process
requirement verified by the merge-gate checklist and the presence of the release
artifacts, not by a tagged automated test (consistent with FRG-PROC-001..012).

## A. Spec + traceability

- [ ] A.1 Amend **FRG-PROC-013** in `openspec/specs/dev-process/spec.md` (via this
      change's `specs/dev-process/spec.md` delta, synced at archive): a release =
      CHANGELOG entry + `pyproject.toml` version + annotated tag + published GitHub
      Release; retroactive to existing tags. Registry row stays `active` (process,
      not milestone-bound); traceability matrix regenerated; `tools/trace.py` exit 0.
      [FRG-PROC-013]

## B. Release record — back-fill + version

- [ ] B.1 Create repository-root `CHANGELOG.md` (Keep-a-Changelog style, most-recent
      first) with a reconstructed entry for every existing tag v0.1.0..v0.2.8 —
      Added/Changed/Fixed/Security + FRG refs + upgrade notes — sourced from tag
      messages and archived change proposals. [FRG-PROC-013]
- [ ] B.2 Bump `backend/pyproject.toml` `version` `0.1.0` → `0.2.8` (current released
      state on `main`). Add a one-line pointer to `CHANGELOG.md` in `README.md`. [FRG-PROC-013]
- [ ] B.3 Publish a GitHub Release (`gh release create <tag> --title … --notes …`) for
      each of v0.1.0..v0.2.8, body = its CHANGELOG entry. (Tags already exist and are
      pushed; releases are additive and never move a tag.) [FRG-PROC-013]

## C. Merge-gate checklist

- [ ] C.1 Expand `docs/process/commit-standard.md` merge-gate step 8: the release step
      now requires the CHANGELOG entry + `pyproject.toml` version bump **pre-merge**,
      and the annotated tag + published GitHub Release **post-merge** (same gate),
      from the same CHANGELOG entry. [FRG-PROC-013, FRG-PROC-011]

## D. Gate

- [ ] D.1 `tools/trace.py` exit 0, `tools/soup_check.py` exit 0 (no SOUP change); full
      backend suite green (unchanged — no code touched); pre-merge review of the diff;
      archive the change (sync the FRG-PROC-013 delta to baseline); `--no-ff` merge to
      `main` with the suite green. **No tag for this change** (owner decision). [FRG-PROC-007]
