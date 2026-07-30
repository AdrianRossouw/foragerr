#!/usr/bin/env python3
"""Merge-gate scanner for comment hygiene (FRG-PROC-023).

Scans committed non-product text — code comments, docstrings, test
names, sample-config comments, and committed docs outside the
README/manual controlled documents — for two classes of defect:

  - **environment-specific values** that are true only of one deployment
    (host:port literals other than the product's documented default,
    private/CGNAT/link-local addresses, tailnet hostnames,
    home-directory and OS-user filesystem paths, operator email
    addresses);
  - **review provenance** in code comments ("gate finding", "per
    review") instead of the invariant the comment exists to state.

What is *mechanically* detectable stops there. Container names, bare
port numbers, session dates and real-world titles are shapes that are
legitimate almost everywhere (a date is a date; a name is a name), so a
regex for them would cost more in false positives than it earns: those
belong to the review gate's human comment-hygiene pass and to the
optional local denylist.

Detection is by *pattern class*, never by a list of specific
environment values: nothing operator-specific is committed inside this
checker. Operator-specific literals (real collection titles, rig
hostnames) belong in a gitignored local denylist
(``tools/comment_check_local_denylist.txt`` by default, overridable
with ``--denylist`` or ``FORAGERR_COMMENT_DENYLIST``), one Python
regex per line. That pass needs no comment extraction, so it runs over
the full text of every tracked text file — fixture corpora included.
When no denylist is present the tool notes it, skips that pass, and
exits on the generic pass alone, so fresh clones and CI stay green.

Legitimate hits are declared in ``tools/comment_check_allow.txt``
(path glob + explicitly enumerated rule names + rationale). Exits 0
when clean, 1 with ``file:line [rule]`` findings, 2 on a configuration
or invocation error — the gate contract of ``tools/soup_check.py`` and
``tools/risk_register_check.py``.

Usage: ``python tools/comment_check.py [root] [--denylist PATH]``. The
standard it enforces is ``docs/process/code-comments.md``.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import io
import os
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
DENYLIST_ENV = "FORAGERR_COMMENT_DENYLIST"
ALLOWLIST = "tools/comment_check_allow.txt"

#: A file larger than this, or one holding a NUL byte, is treated as binary
#: and skipped with a count rather than decoded.
MAX_TEXT_BYTES = 2 * 1024 * 1024


class ConfigError(Exception):
    """A malformed allowlist or denylist: exit 2, never a silent pass."""


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
    LOCAL_DENYLIST,
)

#: Directory names the non-git fallback walk must never descend into: build
#: and tool caches are not committed text, and an agent-state directory can
#: hold transcripts of exactly the values this tool looks for.
WALK_SKIP_PARTS = (".git", ".venv", "venv", "node_modules", ".claude-memory", "__pycache__")


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
    """Fallback discovery for trees that are not git worktrees (tests).

    Only the parts *below* root are tested, so a repository that itself sits
    inside a skipped directory name is still scanned.
    """
    keep = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in WALK_SKIP_PARTS or part.startswith(".claude") for part in rel.parts):
            continue
        keep.append(rel)
    return keep


def text_files(root: Path = ROOT) -> list[Path]:
    """Every candidate text path in scope, in scan order.

    Extension filtering belongs to the generic rules, which need to know how
    to find a comment; the local-denylist pass needs no such knowledge and
    runs over all of these.
    """
    rels = _tracked_files(root)
    if rels is None:
        rels = _walked_files(root)
    return [
        rel
        for rel in rels
        if not any(fnmatch.fnmatch(rel.as_posix(), pat) for pat in EXCLUDED)
    ]


def has_extractable_comments(rel: Path) -> bool:
    """Whether the generic rules know how to isolate this file's comments."""
    return rel.suffix in PY_EXTS | CSTYLE_EXTS | HASH_EXTS | DOC_EXTS or rel.name in HASH_NAMES


def candidate_files(root: Path = ROOT) -> list[Path]:
    """Repo-relative paths the generic (comment-extracting) rules scan."""
    return [rel for rel in text_files(root) if has_extractable_comments(rel)]


def read_text_file(path: Path) -> str | None:
    """Decoded contents, or None when the file is binary/oversized/unreadable."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) > MAX_TEXT_BYTES or b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


# --------------------------------------------------------------------------
# extraction: (line number, text) units of committed non-product text
# --------------------------------------------------------------------------


@dataclass
class Extracted:
    """Non-product text of one file, plus any signs it was misparsed."""

    kind: str
    units: list[tuple[int, str]]
    notes: tuple[str, ...] = ()


def _quote_notes(lines: tuple[int, ...]) -> tuple[str, ...]:
    if not lines:
        return ()
    shown = ", ".join(str(n) for n in lines[:5])
    more = f" (+{len(lines) - 5} more)" if len(lines) > 5 else ""
    return (
        f"unbalanced quote on line {shown}{more} — comment extraction on those "
        "lines may be incomplete",
    )


def _comment_units(
    text: str, line_comments: tuple[str, ...], block: tuple[str, str] | None
) -> tuple[list[tuple[int, str]], tuple[int, ...]]:
    """Comment content of a C-style or hash-commented source, line by line.

    Quote-aware, so a `//` or `#` inside a string literal is code, not a
    comment; block comments yield one unit per line they span.

    Quote state SHALL NOT survive a newline. In these languages a string
    literal essentially never spans a raw line break, while the shapes that
    do leave a quote open — a TOML `'''` delimiter, a JS regex literal, an
    apostrophe in JSX text, nested shell quoting — are common. Carrying the
    state across lines therefore does not protect anything; it silently
    blinds the scanner to every later comment in the file, which is the
    failure mode a gate can least afford. Lines that both left a quote open
    *and* held a comment marker inside it are returned, because only there
    could a real comment have been swallowed.
    """
    units: list[tuple[int, str]] = []
    unbalanced: list[int] = []
    markers = line_comments + ((block[0],) if block else ())

    def _swallowed_a_marker(start: int, stop: int) -> bool:
        region = text[start:stop]
        return any(tok in region for tok in markers)

    i, line, n = 0, 1, len(text)
    quote, quote_start = "", 0
    while i < n:
        ch = text[i]
        if ch == "\n":
            if quote:
                if _swallowed_a_marker(quote_start, i):
                    unbalanced.append(line)
                quote = ""
            line += 1
            i += 1
            continue
        if quote:
            if ch == "\\":
                # An escaped newline is a real continuation, so the literal
                # keeps its quote across it.
                if i + 1 < n and text[i + 1] == "\n":
                    line += 1
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "\"'`":
            quote, quote_start = ch, i
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
    if quote and _swallowed_a_marker(quote_start, n):
        unbalanced.append(line)
    return units, tuple(unbalanced)


def python_units(text: str) -> Extracted:
    """Comments, docstrings and test-function names of a Python source."""
    units: list[tuple[int, str]] = []
    notes: list[str] = []
    lines = text.splitlines()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                units.append((tok.start[0], tok.string))
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        notes.append(f"tokenize failed ({exc.__class__.__name__}) — comments may be missed")
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        notes.append(f"parse failed ({exc.__class__.__name__}) — docstrings were not scanned")
        return Extracted("code", units, tuple(notes))
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
    return Extracted("code", units, tuple(notes))


#: Vitest/Playwright test labels are non-product text living in a string
#: argument, so they are collected on top of the comment units.
JS_LABEL_RX = re.compile(r"\b(?:it|test|describe)(?:\.\w+)?\(\s*(['\"`])(?P<label>[^'\"`]*)\1")


def cstyle_units(text: str) -> Extracted:
    units, unbalanced = _comment_units(text, ("//",), ("/*", "*/"))
    for m in JS_LABEL_RX.finditer(text):
        units.append((text.count("\n", 0, m.start()) + 1, m.group("label")))
    return Extracted("code", units, _quote_notes(unbalanced))


def hash_units(text: str) -> Extracted:
    units, unbalanced = _comment_units(text, ("#",), None)
    return Extracted("code", units, _quote_notes(unbalanced))


def doc_units(text: str) -> Extracted:
    return Extracted("doc", list(enumerate(text.splitlines(), 1)))


def units_for(rel: Path, text: str) -> Extracted:
    """Non-product text of a file in scope; kind is "code" or "doc"."""
    if rel.suffix in PY_EXTS:
        return python_units(text)
    if rel.suffix in CSTYLE_EXTS:
        return cstyle_units(text)
    if rel.suffix in DOC_EXTS:
        return doc_units(text)
    return hash_units(text)


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


#: Hostname shapes that name one machine rather than a class of machine.
#: Matched case-insensitively: a host name is case-insensitive, so LOCALHOST
#: and Localhost pin an instance exactly as surely as localhost does.
_HOST_ALT = (
    r"(?:\b(?:localhost|host\.docker\.internal|[A-Za-z0-9-]+\.ts\.net"
    r"|(?:\d{1,3}\.){3}\d{1,3})|\[::1\])"
)

RULES: tuple[Rule, ...] = (
    Rule(
        "host-port",
        re.compile(_HOST_ALT + r":(?P<port>\d{2,5})\b", re.I),
        "host:port literal pins one instance; only the documented default port is product fact",
        is_violation=_port_is_env_specific,
    ),
    Rule(
        "port-literal",
        # "port"/"PORT" may be the tail of an env var (FORAGERR_PORT=…) but not
        # of a word ("Report 2024" is prose, not a port). The optional quote
        # covers the quoted YAML/JSON `PORT: "…"` shape.
        re.compile(r"(?:(?<=_)|\b)(?:[Pp]ort|PORT)\s*[ =:(]\s*[\"']?(?P<port>\d{4,5})\b"),
        "port number pins one instance",
        is_violation=_port_is_env_specific,
    ),
    Rule(
        "private-ip",
        # RFC 1918 plus the two ranges a Tailscale/home deployment actually
        # hands out: CGNAT 100.64/10 (tailnet peers) and link-local 169.254/16.
        re.compile(
            r"\b(?:10\.\d{1,3}"
            r"|192\.168"
            r"|172\.(?:1[6-9]|2\d|3[01])"
            r"|169\.254"
            r"|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7]))"
            r"\.\d{1,3}\.\d{1,3}\b"
        ),
        "private, CGNAT or link-local address is true only of one network",
    ),
    Rule(
        "tailnet-host",
        re.compile(r"\b[A-Za-z0-9-]+\.ts\.net\b", re.I),
        "a *.ts.net name is one operator's tailnet peer",
    ),
    Rule(
        "local-path",
        # Case matters here: /Users is macOS's directory, /users is not, and a
        # lowercase /home/ path is not the same string as a Windows drive
        # prefix. Only the Windows prefix is matched case-insensitively,
        # because a drive letter and `C:\users\` genuinely vary in case.
        re.compile(
            r"(?:/Users/|/home/|/root/|/Volumes/|/tmp/)[A-Za-z0-9._-]+"
            r"|(?i:[A-Za-z]:\\Users\\)[A-Za-z0-9._-]+"
            r"|(?<![A-Za-z0-9_~])~/[A-Za-z0-9._-]+"
            r"|\$\{?HOME\}?/[A-Za-z0-9._-]+"
        ),
        "absolute or home-relative path outside the container's own layout is one machine's disk",
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

DENYLIST_RULE = "local-denylist"
RULE_NAMES = frozenset({rule.name for rule in RULES} | {DENYLIST_RULE})


# --------------------------------------------------------------------------
# allowlist / local denylist
# --------------------------------------------------------------------------


@dataclass
class AllowEntry:
    glob: str
    rules: frozenset[str]
    used: bool = False


@dataclass
class Allowlist:
    """Committed exceptions: `<path glob> <rule[,rule]>  # rationale`.

    Rule names are enumerated, never wildcarded: a blanket exemption is the
    one shape that cannot be reviewed, because it also licenses every rule
    added after it was written.
    """

    entries: list[AllowEntry] = field(default_factory=list)

    @classmethod
    def load(cls, root: Path) -> "Allowlist":
        path = root / ALLOWLIST
        entries: list[AllowEntry] = []
        if path.is_file():
            for lineno, raw in enumerate(path.read_text().splitlines(), 1):
                line = raw.split("#", 1)[0].strip()
                if not line:
                    continue
                parts = line.split()
                where = f"{ALLOWLIST}:{lineno}"
                if len(parts) < 2:
                    raise ConfigError(
                        f"{where}: entry needs a path glob and at least one rule name, "
                        f"got {line!r}"
                    )
                names = frozenset(n for n in parts[1].split(",") if n)
                if "*" in names:
                    raise ConfigError(
                        f"{where}: '*' is not a rule name — enumerate the rules this "
                        f"path is exempt from ({', '.join(sorted(RULE_NAMES))})"
                    )
                unknown = sorted(names - RULE_NAMES)
                if unknown:
                    raise ConfigError(
                        f"{where}: unknown rule name(s) {', '.join(unknown)}; "
                        f"known rules are {', '.join(sorted(RULE_NAMES))}"
                    )
                entries.append(AllowEntry(parts[0], names))
        return cls(entries)

    def allows(self, rel: Path, rule: str) -> bool:
        """Whether `rule` is declared legitimate for `rel`, marking the entry used."""
        posix = rel.as_posix()
        hit = False
        for entry in self.entries:
            if rule in entry.rules and fnmatch.fnmatch(posix, entry.glob):
                entry.used = True
                hit = True
        return hit

    def unused(self) -> list[AllowEntry]:
        return [entry for entry in self.entries if not entry.used]


def load_local_denylist(path: Path) -> list[re.Pattern] | None:
    """Operator-private literals to flag, or None when there are none.

    Each non-comment line is a **Python regular expression** (matched
    case-insensitively): a literal that contains regex metacharacters must
    be escaped by the operator. An unparseable line is a configuration
    error, not a silent fall back to substring matching — a denylist that
    quietly stops meaning what it says is worse than one that refuses to
    load.

    A file that exists but holds no patterns is indistinguishable in effect
    from an absent one, so it is reported as absent.

    The file is gitignored by design: the values it holds (real collection
    titles, rig hostnames) must not be committed anywhere, including inside
    this checker.
    """
    if not path.is_file():
        return None
    patterns = []
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            patterns.append(re.compile(line, re.I))
        except re.error as exc:
            raise ConfigError(f"{path}:{lineno}: not a valid Python regex ({exc})") from exc
    return patterns or None


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


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    has_denylist: bool = False
    #: Misparse signals and unused allowlist entries: they do not decide the
    #: exit code, but a silently mis-scanned file is how a gate rots.
    notes: list[str] = field(default_factory=list)
    #: Paths that could not be decoded as text.
    skipped: list[str] = field(default_factory=list)


def _excerpt(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= 110 else flat[:107] + "..."


def check(root: Path = ROOT, denylist_path: Path | None = None) -> Report:
    """Scan `root` and report. Pure: no printing and no exit."""
    allowlist = Allowlist.load(root)
    denylist_path = denylist_path or root / LOCAL_DENYLIST
    denylist = load_local_denylist(denylist_path)
    report = Report(counts={"text_files": 0, "files": 0, "units": 0, "skipped": 0})
    # The denylist holds the very literals it hunts for, so it is never its
    # own scan target even when an override puts it inside the tree.
    try:
        own_denylist = denylist_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        own_denylist = None

    for rel in text_files(root):
        if rel.as_posix() == own_denylist:
            continue
        text = read_text_file(root / rel)
        if text is None:
            report.counts["skipped"] += 1
            report.skipped.append(rel.as_posix())
            continue
        report.counts["text_files"] += 1

        if has_extractable_comments(rel):
            extracted = units_for(rel, text)
            report.counts["files"] += 1
            report.counts["units"] += len(extracted.units)
            for note in extracted.notes:
                report.notes.append(f"{rel.as_posix()}: {note}")
            for lineno, unit in extracted.units:
                for rule in RULES:
                    if extracted.kind not in rule.kinds:
                        continue
                    for m in rule.pattern.finditer(unit):
                        if rule.is_violation is not None and not rule.is_violation(m):
                            continue
                        if allowlist.allows(rel, rule.name):
                            break
                        report.findings.append(
                            Finding(rel.as_posix(), lineno, rule.name, _excerpt(unit))
                        )
                        break

        if denylist:
            for lineno, line in enumerate(text.splitlines(), 1):
                for pattern in denylist:
                    if not pattern.search(line):
                        continue
                    if allowlist.allows(rel, DENYLIST_RULE):
                        break
                    report.findings.append(
                        Finding(rel.as_posix(), lineno, DENYLIST_RULE, _excerpt(line))
                    )
                    break

    for entry in allowlist.unused():
        report.notes.append(
            f"{ALLOWLIST}: unused entry {entry.glob} "
            f"[{','.join(sorted(entry.rules))}] — delete it or narrow it"
        )

    report.findings.sort(key=lambda f: (f.path, f.line, f.rule))
    report.has_denylist = denylist is not None
    return report


def resolve_denylist(root: Path, override: str | None) -> Path:
    """Denylist location: explicit flag, then environment, then the default."""
    chosen = override or os.environ.get(DENYLIST_ENV)
    return Path(chosen).expanduser().resolve() if chosen else root / LOCAL_DENYLIST


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="comment_check",
        description="Comment-hygiene gate scanner (FRG-PROC-023).",
    )
    parser.add_argument("root", nargs="?", help="repository root to scan (default: this repo)")
    parser.add_argument(
        "--denylist",
        help=f"operator-private literal denylist (default: <root>/{LOCAL_DENYLIST}, "
        f"or ${DENYLIST_ENV})",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    root = Path(args.root).expanduser().resolve() if args.root else ROOT
    if not root.is_dir():
        print(f"comment_check: {root} is not a directory", file=sys.stderr)
        return 2

    denylist_path = resolve_denylist(root, args.denylist)
    try:
        report = check(root, denylist_path=denylist_path)
    except ConfigError as exc:
        print(f"comment_check: configuration error: {exc}", file=sys.stderr)
        return 2

    if not report.has_denylist:
        print(
            f"comment_check: no {denylist_path} — local-literal pass skipped "
            "(generic pass ran)",
            file=sys.stderr,
        )
    for note in report.notes:
        print(f"comment_check: note: {note}", file=sys.stderr)
    if report.skipped:
        print(
            f"comment_check: skipped {len(report.skipped)} undecodable file(s): "
            + ", ".join(report.skipped[:10])
            + (" ..." if len(report.skipped) > 10 else ""),
            file=sys.stderr,
        )

    if not report.counts["text_files"]:
        print(f"comment_check: no text files found under {root}", file=sys.stderr)
        return 2

    if report.findings:
        print(
            f"comment_check: {len(report.findings)} finding(s) across "
            f"{report.counts['files']} files:",
            file=sys.stderr,
        )
        for f in report.findings:
            print(f"  - {f}", file=sys.stderr)
        print(
            "comment_check: see docs/process/code-comments.md (FRG-PROC-023); "
            f"declare a legitimate hit in {ALLOWLIST}",
            file=sys.stderr,
        )
        return 1
    print(
        f"comment_check: {report.counts['files']} files, "
        f"{report.counts['units']} text units clean "
        f"({report.counts['text_files']} text files scanned for local literals)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
