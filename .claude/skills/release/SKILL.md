---
name: release
description: Cut a foragerr release — version bump, CHANGELOG, annotated tag, and GitHub Release — per FRG-PROC-013. Use when the user wants to release, tag a version, or publish a GitHub Release for a change.
license: MIT
compatibility: Requires git and the gh CLI. Run from the repo root.
metadata:
  author: foragerr
  version: "1.0"
---

Cut a release for foragerr.

This skill is **subordinate to the spec**: `FRG-PROC-013 — Release tagging`
(`openspec/specs/dev-process/spec.md`) owns the scheme, and item 9 of the
merge-gate checklist (`docs/process/commit-standard.md`) owns the gate ordering.
This skill only *executes* that process mechanically and consistently. If this
skill and the spec ever disagree, the spec wins — fix the skill.

A release is **not complete** until all four exist: the `CHANGELOG.md` entry,
the annotated tag, the pushed `main`, and the published GitHub Release. Do not
report a release as done until you have verified all four.

## When to use

The user says "release", "cut a release", "tag it", "bump the version", or
"publish the release" — for a change that is ready to land (or has just landed)
on `main`.

## The version number

- **SemVer, allocated at merge time — never at branch-creation time.** The next
  version is a global sequential resource (like a requirement ID). Deciding it
  early, while other change branches are open, is what causes out-of-order
  collisions. Decide it when you are about to merge, from the current state of
  `main`.
- **Increment rule (pre-1.0, FRG-PROC-013):** completing a milestone sets the
  MINOR line; each subsequent merged change within a milestone increments PATCH.
  In practice during a dogfood series that means the next PATCH: read the latest
  tag (`git tag --sort=-creatordate | head -1`) and add one to the patch digit
  unless the change closes a milestone.
- If two release-bearing branches are ever open at once, expect the second merge
  to **conflict** on the `version =` line and the CHANGELOG insertion point.
  That conflict is the safety net working — renumber the loser to the next PATCH
  and resolve. There is no silent-bad-release path.

## Procedure

### Pre-merge — in the change branch itself (same merged change)

FRG-PROC-013 requires the CHANGELOG entry and the version bump to land in the
**same change** as the code they describe. Do these on the change branch, as the
**last commit before merging**, when the version number is known:

1. **Bump the version.** Edit `backend/pyproject.toml` `version = "X.Y.Z"`.
   - This is the ONLY version location (the frontend `package.json` stays
     `0.0.0`).
   - Edit the single line with an exact string replace. **Never** rewrite the
     file with a read-then-truncate pattern (`open(p,'w').write(open(p).read())`)
     — that has blanked `pyproject.toml` mid-release before. After editing,
     verify it parses:
     `backend/.venv/bin/python -c "import tomllib; print(tomllib.load(open('backend/pyproject.toml','rb'))['project']['version'])"`
2. **Write the CHANGELOG entry** at the top of `CHANGELOG.md`, immediately above
   the previous release block:
   - Heading `## [vX.Y.Z] — YYYY-MM-DD` (use the real current date).
   - A one-line summary, then the user/admin-facing changes grouped as
     **Added / Changed / Fixed / Security** (only the groups that apply).
   - Cite the `FRG-...` requirement ids the release delivers, and any upgrade /
     migration notes.
3. **Commit** on the change branch. Subject is Conventional Commits, e.g.
   `docs(spec): vX.Y.Z CHANGELOG + version bump for <change-id>`.
   - **Subject ≤ 72 *bytes*, not characters** — the commit-msg hook counts bytes.
     A `—` em-dash is 3 bytes; two of them can silently push a "68-char" subject
     over the limit. Prefer ASCII `-` in subjects, or keep them short.
   - Trailer: `Refs: <the change's FRG ids>, FRG-PROC-013` (blank line before
     `Refs:`, and `Co-Authored-By:` on the **next line with no blank between** —
     git's trailer parser needs them contiguous or trace.py won't see the refs).

### Merge gate

Run the full merge-gate checklist (`docs/process/commit-standard.md` §Merge-gate)
before `--no-ff`: tests green, `tools/trace.py` / `tools/soup_check.py` /
`tools/risk_register_check.py` all exit 0, review pass done, registry flipped,
change archived. (A future `/gate` skill will encapsulate this; until then, run
the checklist.) Then merge:

```
git checkout main
git merge --no-ff <change-branch> -m "Merge <change-branch>: vX.Y.Z — <summary>"
```

Merge/version-bump commit subjects follow the same ≤72-byte rule.

### Post-merge — the single post-merge step

Immediately after the merge commit exists, from the same gate:

1. **Annotated tag** on the merge commit — message names the change id and its
   FRG refs:
   ```
   git tag -a vX.Y.Z -m "vX.Y.Z — <summary> (<change-id>; FRG-...)"
   ```
2. **Push** `main` and the tag to `origin` (both — the tag is a restore point):
   ```
   git push origin main
   git push origin vX.Y.Z
   ```
3. **GitHub Release** carrying the CHANGELOG entry as its body. Extract just this
   version's block and pass it as the notes:
   ```
   awk '/^## \[vX.Y.Z\]/{f=1;next} /^## \[/{f=0} f' CHANGELOG.md > /tmp/relnotes.md
   gh release create vX.Y.Z --title "vX.Y.Z — <summary>" --notes-file /tmp/relnotes.md
   ```
   - **In this sandbox**, prefix `gh` with `GH_TOKEN=placeholder` — the proxy
     injects the real contents-R/W token for `api.github.com`
     (see the `gh-releases-sandbox` memory).

### Verify

Confirm all four exist before reporting done:
- `git tag -l vX.Y.Z` shows the tag;
- `git log origin/main -1` includes the merge;
- `grep '## \[vX.Y.Z\]' CHANGELOG.md` finds the entry;
- `GH_TOKEN=placeholder gh release view vX.Y.Z --json url` returns the release URL.

## Guardrails

- **Tags are immutable.** Never move or delete a pushed tag. A bad release is
  corrected only by a **new PATCH** tag (FRG-PROC-013).
- **Never commit the version bump / CHANGELOG directly on `main`** — the
  pre-commit hook forbids commits on `main`, and FRG-PROC-013 requires them in
  the change branch. If a change already merged without them (as happened once),
  do them on a small dedicated release branch and merge that, rather than
  committing on `main`.
- **Don't stamp the version early.** See "The version number" above.
- Regenerate the traceability matrix if the release commit changed registry rows;
  if `trace.py` only reshuffles the rolling commit-window in `matrix.md`, restore
  it (`git checkout -- docs/traceability/matrix.md`) rather than committing on
  `main`.

## Scope: current (pre-1.0) vs 1.0

**Active now (pre-1.0):** the single-channel PATCH-per-change cadence above.
Pre-1.0 releases may break with migration notes.

**Grows at 1.0 (M10 go-live — NOT yet in effect; do not apply these until the
M10 release-process change lands).** When 1.0 work begins, extend this skill per
the `release-process-idea` / `one-dot-zero-cut` direction:
- **dev / rc / release channels** — a `dev` → `rc` → `release` SemVer promotion
  flow rather than one channel;
- **release-gate-as-coverage-backstop** — the release gate additionally asserts a
  coverage floor, catching requirements that slipped a tagged test;
- **pentest decision** — a go-live security review / penetration-test gate before
  the 1.0 tag;
- **strict SemVer on public surfaces** (REST, OPDS, config, env vars) from 1.0
  onward — breaking changes bump MAJOR, not a footnote.
Keep this section the single place that tracks the growth, and move items up into
"Active now" as they land.
