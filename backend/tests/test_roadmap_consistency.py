"""Roadmap single-source-of-truth checks (FRG-PROC-018).

`docs/roadmap.md` is the only controlled document allowed to carry
forward-looking content; every other controlled document links to it rather
than restating unshipped plans. Two committed-text checks, run at every merge
gate (same pattern as `test_public_labelling.py`), keep that invariant true as
the project ships:

  - **Containment** — future-milestone tokens (``M5`` and up, ``M10+``
    included) and
    planned-phrasing markers may not appear in controlled documents other than
    the roadmap, save an explicit file+token allowlist. ``M4`` is deliberately
    excluded: it is the current milestone, handled by the corrective sweep, not
    by the scanner (design decision 6), so the check does not churn every time
    the current milestone increments.
  - **Freshness** — no ``FRG-*`` id the roadmap presents as planned may already
    be ``implemented``/``verified`` in the requirements registry (shipping an
    item forces the roadmap edit in the same change), and every cited id must
    exist (typo guard). Registry parsing is delegated to ``tools/trace.py`` so
    this file and the matrix generator agree on what a registered row is.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _tracked(paths):
    """Keep only git-tracked files, so a local scratch note under docs/manual/
    cannot fail the gate on one machine only."""
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", *[str(p) for p in paths]],
        capture_output=True, text=True, cwd=REPO_ROOT,
    ).stdout
    tracked = {REPO_ROOT / rel for rel in out.split("\0") if rel}
    return [p for p in paths if p in tracked]


def _load_trace():
    spec = importlib.util.spec_from_file_location(
        "trace", REPO_ROOT / "tools" / "trace.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REGISTRY = _load_trace().registry_rows()

# Controlled documents scanned for forward-looking content. docs/roadmap.md is
# intentionally *not* here — it is the one document allowed to describe unshipped
# work.
SCANNED_DOCS = _tracked([
    REPO_ROOT / "README.md",
    *sorted((REPO_ROOT / "docs" / "manual").rglob("*.md")),
])

# Future-milestone token: M5..M9 (and M10+, so the check survives the project
# outliving single-digit milestones) as a standalone word, either case. M4 (the
# current milestone) is excluded on purpose — see module docstring / design
# decision 6.
MILESTONE_RE = re.compile(r"\bM(?:[5-9]|[1-9]\d+)\b", re.IGNORECASE)

# Planned-phrasing markers, matched case-insensitively. Kept to compound phrases
# that read as roadmap prose; bare words ("planned", "future", "upcoming") are
# omitted because the manual uses them for legitimate current-state descriptions
# — "planned screens appear in the release that ships them" (web-ui.md), the
# "future" monitoring option and "future metadata refreshes" (library.md),
# "Future candidates are matched" (downloads.md).
PHRASE_MARKERS = (
    "planned, not yet shipped",
    "not yet shipped",
    "will arrive",
    "upcoming milestone",
    "future work",
)

# Explicit (relative_path, token) allowlist for incidental forward references
# that must remain. Each entry needs an inline justification comment so reviewers
# see it in the diff. Expected empty after the corrective sweep.
ALLOWLIST: tuple[tuple[str, str], ...] = (
    # (none)
)


@pytest.mark.req("FRG-PROC-018")
def test_forward_looking_content_is_contained_to_the_roadmap():
    """No future-milestone token or planned-phrasing marker outside the roadmap."""
    hits: list[str] = []
    for path in SCANNED_DOCS:
        rel = str(path.relative_to(REPO_ROOT))
        text = path.read_text()
        for token in {m.group(0) for m in MILESTONE_RE.finditer(text)}:
            if (rel, token) not in ALLOWLIST:
                hits.append(f"{rel}: {token!r}")
        lowered = text.lower()
        for marker in PHRASE_MARKERS:
            if marker in lowered and (rel, marker) not in ALLOWLIST:
                hits.append(f"{rel}: {marker!r}")
    assert not hits, (
        "forward-looking content must live only in docs/roadmap.md "
        "(FRG-PROC-018); found in controlled documents: " + "; ".join(sorted(hits))
    )


@pytest.mark.req("FRG-PROC-018")
def test_roadmap_cited_ids_are_registered_and_not_yet_shipped():
    """Every FRG id the roadmap presents as planned must exist and be unshipped.

    Only milestone sections (after the first ``## `` heading) are scanned: the
    intro legitimately cites the governing FRG-PROC-018, which is implemented —
    a citation of authority, not a planned item."""
    roadmap = (REPO_ROOT / "docs" / "roadmap.md").read_text()
    sections = roadmap.split("\n## ", 1)
    body = sections[1] if len(sections) > 1 else ""
    assert body, "docs/roadmap.md has no milestone sections — layout changed?"
    problems: list[str] = []
    for line in body.splitlines():
        if re.search(r"FRG-[A-Z]+-\d{3}\W{0,2}\.\.", line):
            problems.append(
                "id-range shorthand ('..') hides interior ids from this check — "
                f"spell every planned id out (line: {line.strip()!r})"
            )
        for rid in re.findall(r"FRG-[A-Z]+-\d{3}", line):
            row = REGISTRY.get(rid)
            if row is None:
                problems.append(
                    f"{rid} is cited in the roadmap but absent from the registry "
                    f"(line: {line.strip()!r})"
                )
            elif row["status"] in ("implemented", "verified", "withdrawn"):
                problems.append(
                    f"{rid} is listed as planned in the roadmap but the registry "
                    f"says {row['status']!r} — remove or rework the entry "
                    f"(line: {line.strip()!r})"
                )
    assert not problems, "; ".join(problems)


@pytest.mark.req("FRG-PROC-018")
@pytest.mark.req("FRG-PROC-014")
def test_roadmap_lists_archive_import_as_future_work():
    """The roadmap is where the public-domain archive import is recorded as
    future work (FRG-PROC-014's obligation, moved here from the README by
    roadmap-single-source). The Humble Bundle importer used to be pinned here
    too, but it shipped in m6-humble-source, so FRG-PROC-014 was amended to
    require only the archive import as the still-future example (the Humble
    entry now describes a shipped feature, not forward-looking work). The
    Sources milestone section must still exist — the milestone is not closed
    (the companion browser extension remains planned)."""
    roadmap_path = REPO_ROOT / "docs" / "roadmap.md"
    assert roadmap_path.exists(), "docs/roadmap.md must exist (FRG-PROC-018)"
    roadmap = roadmap_path.read_text()
    sections = re.split(r"^## ", roadmap, flags=re.M)
    body = "## ".join(sections[1:])
    sources = next(
        (s for s in sections[1:] if "Sources" in s.splitlines()[0]),
        None,
    )
    assert sources is not None, (
        "docs/roadmap.md must keep a Sources milestone section"
    )
    assert "public-domain archive import" in body.lower(), (
        "the roadmap's milestone sections must list the public-domain archive "
        "import as future work"
    )
