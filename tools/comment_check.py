#!/usr/bin/env python3
"""Merge-gate scanner for comment hygiene (FRG-PROC-023).

Scans committed non-product text — code comments, docstrings, test
names, sample-config comments, and committed docs outside the
README/manual controlled documents — for two classes of defect:

  - **environment-specific values** that are true only of one deployment
    (host:port literals other than the product's documented default,
    private IP addresses, home-directory/scratch filesystem paths,
    operator email addresses);
  - **review provenance** in code comments ("gate finding", "per
    review", a reviewer's name) instead of the invariant the comment
    exists to state.

Detection is by *pattern class*, never by a list of specific
environment values: nothing operator-specific is committed inside this
checker. Operator-specific literals (real collection titles, rig
hostnames) belong in an optional gitignored local denylist
(``tools/comment_check_local_denylist.txt``, one regex per line); when
that file is absent the tool prints a notice, skips that pass, and
exits on the generic pass alone, so fresh clones and CI stay green.

Legitimate hits are declared in ``tools/comment_check_allow.txt``
(path glob + rule names + rationale). Exits 0 when clean, 1 with
``file:line [rule]`` findings otherwise — the gate contract of
``tools/soup_check.py`` and ``tools/risk_register_check.py``.

Usage: ``python tools/comment_check.py [root]``. The standard it
enforces is ``docs/process/code-comments.md``.
"""

from __future__ import annotations

import ast
import fnmatch
import io
import re
import subprocess
import sys
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Ports the product itself documents as its default; a loopback literal on
#: one of these is product fact, not an environment value. Any other port
#: pins a specific instance.
PRODUCT_PORTS = frozenset({"8789"})

#: Local-part / domain classes that exist precisely to be unroutable
#: placeholders (RFC 2606 + the commit trailer's noreply address).
EMAIL_ALLOWED_LOCALS = ("noreply", "no-reply")
EMAIL_ALLOWED_DOMAIN_RX = re.compile(
    r"(?:^|\.)(?:example\.(?:com|org|net)|test|invalid|example)$", re.I
)

LOCAL_DENYLIST = "tools/comment_check_local_denylist.txt"
ALLOWLIST = "tools/comment_check_allow.txt"

# --------------------------------------------------------------------------
# file selection
# --------------------------------------------------------------------------

#: Extension -> how to pull the non-product text out of the file.
PY_EXTS = frozenset({".py"})
CSTYLE_EXTS = frozenset({".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css"})
HASH_EXTS = frozenset({".sh", ".yml", ".yaml", ".toml", ".example", ".conf"})
DOC_EXTS = frozenset({".md"})
HASH_NAMES = frozenset({"Dockerfile", ".env.example"})

#: Controlled documents with their own governing requirements
#: (FRG-PROC-011/014/018) and their own checks, plus historical records that
#: must not be rewritten: an archived proposal is the artefact the owner
#: approved, so it is read-only evidence rather than living text.
EXCLUDED = (
    "README.md",
    "docs/manual/*",
    "openspec/changes/archive/*",
    ".reference/*",
    "node_modules/*",
    "*/node_modules/*",
    "dist/*",
    "*/dist/*",
    "_site/*",
    "*.min.js",
    "*-lock.json",
)


def _tracked_files(root: Path) -> list[Path] | None:
    """Paths git would carry into a commit, or None outside a git worktree.

    Untracked-but-not-ignored files are included so a new file is scanned
    before its first commit, not after.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
             "--exclude-standard"],
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if out.returncode != 0:
        return None
    return [Path(p) for p in out.stdout.decode().split("\0") if p]


def _walked_files(root: Path) -> list[Path]:
    """Fallback discovery for trees that are not git worktrees (tests)."""
    return [
        p.relative_to(root)
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git" not in p.parts
    ]


def candidate_files(root: Path = ROOT) -> list[Path]:
    """Repo-relative paths in scope, in scan order."""
    rels = _tracked_files(root)
    if rels is None:
        rels = _walked_files(root)
    keep = []
    for rel in rels:
        posix = rel.as_posix()
        if any(fnmatch.fnmatch(posix, pat) for pat in EXCLUDED):
            continue
        if rel.suffix in PY_EXTS | CSTYLE_EXTS | HASH_EXTS | DOC_EXTS or rel.name in HASH_NAMES:
            keep.append(rel)
    return keep


# --------------------------------------------------------------------------
# extraction: (line number, text) units of committed non-product text
# --------------------------------------------------------------------------


def _comment_units(text: str, line_comments: tuple[str, ...], block: tuple[str, str] | None):
    """Comment content of a C-style or hash-commented source, line by line.

    Quote-aware, so a `//` or `#` inside a string literal is code, not a
    comment; block comments yield one unit per line they span.
    """
    units: list[tuple[int, str]] = []
    i, line, n = 0, 1, len(text)
    quote = ""
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            i += 1
            continue
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            i += 1
            continue
        if block and text.startswith(block[0], i):
            end = text.find(block[1], i + len(block[0]))
            end = n if end < 0 else end + len(block[1])
            for offset, part in enumerate(text[i:end].split("\n")):
                units.append((line + offset, part))
            line += text.count("\n", i, end)
            i = end
            continue
        hit = next((tok for tok in line_comments if text.startswith(tok, i)), None)
        if hit:
            end = text.find("\n", i)
            end = n if end < 0 else end
            units.append((line, text[i:end]))
            i = end
            continue
        i += 1
    return units


def python_units(text: str) -> list[tuple[int, str]]:
    """Comments, docstrings and test-function names of a Python source."""
    units: list[tuple[int, str]] = []
    lines = text.splitlines()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                units.append((tok.start[0], tok.string))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return units
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = node.body[0] if node.body else None
            if (
                isinstance(doc, ast.Expr)
                and isinstance(doc.value, ast.Constant)
                and isinstance(doc.value.value, str)
            ):
                start, end = doc.lineno, (doc.end_lineno or doc.lineno)
                for lineno in range(start, min(end, len(lines)) + 1):
                    units.append((lineno, lines[lineno - 1]))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test"
        ):
            units.append((node.lineno, node.name))
    return units


#: Vitest/Playwright test labels are non-product text living in a string
#: argument, so they are collected on top of the comment units.
JS_LABEL_RX = re.compile(r"\b(?:it|test|describe)(?:\.\w+)?\(\s*(['\"`])(?P<label>[^'\"`]*)\1")


def cstyle_units(text: str) -> list[tuple[int, str]]:
    units = _comment_units(text, ("//",), ("/*", "*/"))
    for m in JS_LABEL_RX.finditer(text):
        units.append((text.count("\n", 0, m.start()) + 1, m.group("label")))
    return units


def hash_units(text: str) -> list[tuple[int, str]]:
    return _comment_units(text, ("#",), None)


def doc_units(text: str) -> list[tuple[int, str]]:
    return list(enumerate(text.splitlines(), 1))


def units_for(rel: Path, text: str) -> tuple[str, list[tuple[int, str]]]:
    """(kind, units) for a file in scope; kind is "code" or "doc"."""
    if rel.suffix in PY_EXTS:
        return "code", python_units(text)
    if rel.suffix in CSTYLE_EXTS:
        return "code", cstyle_units(text)
    if rel.suffix in DOC_EXTS:
        return "doc", doc_units(text)
    return "code", hash_units(text)


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------


def _port_is_env_specific(m: re.Match) -> bool:
    return m.group("port") not in PRODUCT_PORTS


def _email_is_env_specific(m: re.Match) -> bool:
    local, domain = m.group("local").lower(), m.group("domain").lower()
    if local in EMAIL_ALLOWED_LOCALS:
        return False
    return not EMAIL_ALLOWED_DOMAIN_RX.search(domain)


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern
    why: str
    #: "code" restricts a rule to comments/docstrings/test names — rule 1
    #: (provenance) is about what a comment is for, and prose in a process
    #: document may legitimately discuss the review process.
    kinds: tuple[str, ...] = ("code", "doc")
    #: Returns False for a match that is benign (documented default, RFC
    #: 2606 placeholder), so the rule stays a pattern class with an
    #: explicit, committed exception set.
    is_violation: object = None


RULES: tuple[Rule, ...] = (
    Rule(
        "host-port",
        re.compile(
            r"\b(?:localhost|host\.docker\.internal|(?:\d{1,3}\.){3}\d{1,3})"
            r":(?P<port>\d{2,5})\b"
        ),
        "host:port literal pins one instance; only the documented default port is product fact",
        is_violation=_port_is_env_specific,
    ),
    Rule(
        "port-literal",
        # "port"/"PORT" may be the tail of an env var (FORAGERR_PORT=…) but not
        # of a word ("Report 2024" is prose, not a port).
        re.compile(r"(?:(?<=_)|\b)(?:[Pp]ort|PORT)\s*[ =:(]\s*(?P<port>\d{4,5})\b"),
        "port number pins one instance",
        is_violation=_port_is_env_specific,
    ),
    Rule(
        "private-ip",
        re.compile(
            r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"
        ),
        "private-network address is true only of one LAN",
        ),
    Rule(
        "local-path",
        re.compile(
            r"(?:/Users/|/home/)[A-Za-z0-9._-]+|/Volumes/[A-Za-z0-9._-]+"
            r"|/tmp/[A-Za-z0-9._-]+|[A-Za-z]:\\Users\\[A-Za-z0-9._-]+"
        ),
        "absolute path outside the container's own layout is one machine's filesystem",
    ),
    Rule(
        "email",
        re.compile(
            r"\b(?P<local>[A-Za-z0-9._%+-]+)@(?P<domain>[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b"
        ),
        "email address identifies a person; use an RFC 2606 placeholder domain",
        is_violation=_email_is_env_specific,
    ),
    Rule(
        "provenance",
        re.compile(
            r"\bgate (?:finding|review|feedback)"
            r"|\bmerge-gate finding"
            r"|\b(?:per|after|fixed in|found in|from the) review\b"
            r"|\breview(?:ers?)? (?:found|flagged|noted|raised|caught|said)\b"
            r"|\bcode[- ]review\b"
            r"|\breviewer\b"
            r"|\bCodex\b",
            re.I,
        ),
        "a comment states the invariant it protects, never how or when it was reviewed",
        kinds=("code",),
    ),
)


# --------------------------------------------------------------------------
# allowlist / local denylist
# --------------------------------------------------------------------------


@dataclass
class Allowlist:
    """Committed exceptions: `<path glob> <rule[,rule]|*>  # rationale`."""

    entries: list[tuple[str, frozenset[str]]] = field(default_factory=list)

    @classmethod
    def load(cls, root: Path) -> "Allowlist":
        path = root / ALLOWLIST
        entries: list[tuple[str, frozenset[str]]] = []
        if path.is_file():
            for raw in path.read_text().splitlines():
                line = raw.split("#", 1)[0].strip()
                if not line:
                    continue
                parts = line.split()
                rules = frozenset(parts[1].split(",")) if len(parts) > 1 else frozenset({"*"})
                entries.append((parts[0], rules))
        return cls(entries)

    def allows(self, rel: Path, rule: str) -> bool:
        posix = rel.as_posix()
        return any(
            fnmatch.fnmatch(posix, glob) and ("*" in rules or rule in rules)
            for glob, rules in self.entries
        )


def load_local_denylist(root: Path) -> list[re.Pattern] | None:
    """Operator-private literals to flag, or None when the file is absent.

    The file is gitignored by design: the values it holds (real collection
    titles, rig hostnames) must not be committed anywhere, including inside
    this checker.
    """
    path = root / LOCAL_DENYLIST
    if not path.is_file():
        return None
    patterns = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            try:
                patterns.append(re.compile(line, re.I))
            except re.error:
                patterns.append(re.compile(re.escape(line), re.I))
    return patterns


# --------------------------------------------------------------------------
# scan
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    excerpt: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line} [{self.rule}] {self.excerpt}"


def _excerpt(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= 110 else flat[:107] + "..."


def check(root: Path = ROOT) -> tuple[list[Finding], dict[str, int], bool]:
    """Scan `root`, returning (findings, counts, local_denylist_present).

    Pure: no printing and no exit, so tests drive it directly.
    """
    allowlist = Allowlist.load(root)
    denylist = load_local_denylist(root)
    findings: list[Finding] = []
    counts = {"files": 0, "units": 0}

    for rel in candidate_files(root):
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        kind, units = units_for(rel, text)
        counts["files"] += 1
        counts["units"] += len(units)
        for lineno, unit in units:
            for rule in RULES:
                if kind not in rule.kinds or allowlist.allows(rel, rule.name):
                    continue
                for m in rule.pattern.finditer(unit):
                    if rule.is_violation is not None and not rule.is_violation(m):
                        continue
                    findings.append(Finding(rel.as_posix(), lineno, rule.name, _excerpt(unit)))
                    break
        if denylist and not allowlist.allows(rel, "local-denylist"):
            for lineno, line in enumerate(text.splitlines(), 1):
                for pattern in denylist:
                    if pattern.search(line):
                        findings.append(
                            Finding(rel.as_posix(), lineno, "local-denylist", _excerpt(line))
                        )
                        break

    findings.sort(key=lambda f: (f.path, f.line, f.rule))
    return findings, counts, denylist is not None


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    root = Path(args[0]).resolve() if args else ROOT
    findings, counts, has_denylist = check(root)
    if not has_denylist:
        print(f"comment_check: no {LOCAL_DENYLIST} — local-literal pass skipped (generic pass ran)")
    if findings:
        print(
            f"comment_check: {len(findings)} finding(s) across {counts['files']} files:",
            file=sys.stderr,
        )
        for f in findings:
            print(f"  - {f}", file=sys.stderr)
        print(
            "comment_check: see docs/process/code-comments.md (FRG-PROC-023); "
            f"declare a legitimate hit in {ALLOWLIST}",
            file=sys.stderr,
        )
        return 1
    print(f"comment_check: {counts['files']} files, {counts['units']} text units clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
