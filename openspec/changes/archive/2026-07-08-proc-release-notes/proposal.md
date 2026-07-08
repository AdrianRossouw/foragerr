## Why

M2 is complete (v0.2.8) and M3 change 1 (m3-pull-backbone) is ready to tag as
v0.3.0 — but the project's release record is not yet first-class. The eleven
existing tags (v0.1.0..v0.2.8) carry only terse annotated messages; there is no
`CHANGELOG.md` and no GitHub Releases, and the backend `pyproject.toml` version is
still the placeholder `0.1.0`, so the running application misreports its version.

foragerr is a working demonstration of regulated software development, where the
release record should be **auditable and self-documenting** rather than
reconstructable only from tag messages and archived proposals. FRG-PROC-013 already
mandates SemVer tagging on every merge; this change elaborates it so a *release* is a
CHANGELOG entry + a matching version + an annotated tag + a published GitHub Release,
and back-fills that record for the existing tags — landed **before v0.3.0** so the
first tag under the elaborated policy is compliant.

## What Changes

- **Release notes become part of the release (MODIFIED FRG-PROC-013)** — the release
  requirement is elaborated: every release SHALL additionally carry a `CHANGELOG.md`
  entry (Keep-a-Changelog Added/Changed/Fixed/Security + FRG refs + upgrade notes),
  the `backend/pyproject.toml` `version` set to the release version, and a published
  GitHub Release carrying the CHANGELOG entry. The CHANGELOG entry + version bump land
  in the same merged change as the code; the tag + GitHub Release are created in the
  same merge gate immediately after the merge commit. The scheme, MINOR/PATCH rules,
  push-as-restore-point, and immutability from the original requirement are unchanged.

- **`CHANGELOG.md` created and back-filled** — a new repository-root `CHANGELOG.md`
  with a reconstructed entry for every existing tag (v0.1.0..v0.2.8), sourced from tag
  messages and archived change proposals, most-recent first.

- **`pyproject.toml` version corrected** — bumped from the stale `0.1.0` to `0.2.8`
  (the current released state on `main`); the next release (v0.3.0, m3-pull-backbone)
  bumps it to `0.3.0` in its own change per the elaborated requirement.

- **GitHub Releases published for existing tags** — `gh release create` for each of
  v0.1.0..v0.2.8, carrying its CHANGELOG entry as the body.

- **Merge-gate checklist updated** — `docs/process/commit-standard.md` step 8 (the
  release step) is expanded to require the CHANGELOG entry + version bump (pre-merge)
  and the GitHub Release (post-merge, with the tag).

## Capabilities

### Modified Capabilities

- `dev-process`: FRG-PROC-013 elaborated from tag-only to a full release record
  (CHANGELOG + version + tag + GitHub Release), applied retroactively to existing tags.

## Impact

- **Code**: none (no product code). Repository-level artifacts only: new
  `CHANGELOG.md`; `backend/pyproject.toml` `version` bumped `0.1.0` → `0.2.8`;
  `docs/process/commit-standard.md` merge-gate checklist step 8 expanded; a one-line
  README pointer to `CHANGELOG.md`.

- **Tests**: no automated test — FRG-PROC-013 is a process/release requirement whose
  verification is the merge-gate checklist and the presence of the release artifacts,
  not a runtime behavior (consistent with the other FRG-PROC-0xx process requirements,
  which are `active` process rules rather than code with tagged tests). The traceability
  matrix records FRG-PROC-013 as process-verified.

- **DB / runtime**: none. The `pyproject.toml` version string is read for display and
  backup/version labelling; correcting it to `0.2.8` makes those honest and changes no
  behavior.

- **Manual** (FRG-PROC-011): **no user/admin manual change.** `CHANGELOG.md` is the
  top-level release record (developer/release-facing), not user or administrator
  operating documentation, so `docs/manual/` is untouched. `README.md` gains a
  one-line pointer to `CHANGELOG.md` (top-level labelling).

- **Security** (FRG-PROC-006): **none.** No new listener, parser of untrusted input,
  credential, or outbound integration. `gh release create` is developer release
  tooling operating on the project's own private repository; it introduces no new
  attack surface. No threat-model or risk-register change.

- **Dependencies / SOUP** (FRG-PROC-012): **none.** No dependency added or changed;
  `tools/soup_check.py` stays at exit 0.

## Non-goals

- **No product code and no runtime behavior change** — this change touches release
  artifacts and process docs only.

- **No new tag for this change itself.** This housekeeping change merges to `main`
  **untagged** (owner decision, 2026-07-08): it ships no user-facing feature and sits
  on the v0.2.8 line; the next tag remains v0.3.0 for m3-pull-backbone.

- **No CI enforcement of the release record.** The CHANGELOG/version/GitHub-Release
  steps are enforced by the merge-gate checklist (as the other process rules are), not
  a new automated CI gate — that can come later if the manual gate proves insufficient.

- **No rewrite of existing tag messages.** Existing annotated tags are immutable
  (FRG-PROC-013); the back-fill adds CHANGELOG entries and GitHub Releases alongside
  them, never moving or re-messaging a tag.

## Approval

Adrian approved this change on 2026-07-08. At the M3-ch1 gate he directed the
release-notes housekeeping be done **before v0.3.0** and, asked how to sequence it,
chose: **housekeeping first** (this change lands before m3-pull-backbone's tag),
**full retroactive scope** (CHANGELOG + GitHub Releases for v0.1.0..v0.2.8), and this
change itself **untagged**. Recorded per FRG-PROC-009; it also falls within the
standing M2/M3 execution grant as the release-process prerequisite for tagging v0.3.0.
