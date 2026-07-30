"""Comment-hygiene scanner (FRG-PROC-023).

Loads tools/comment_check.py by path (it lives outside the backend package,
next to tools/soup_check.py) and drives its pure `check(root)` against
synthetic tmp_path trees plus the real repository, never mutating the
repository's own files.

The fixture text below deliberately violates the standard it enforces; the
allowlist entry for this file is what keeps the scanner from flagging its
own test data.

Every rule owns at least one fixture that hits it *alone* and an exact
`rules_hit` assertion, so deleting or weakening a rule fails this suite
rather than silently shrinking the gate.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_comment_check():
    spec = importlib.util.spec_from_file_location(
        "comment_check", REPO_ROOT / "tools" / "comment_check.py"
    )
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: the module's dataclasses resolve their own
    # __module__ through sys.modules while the class body is being built.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


comment_check = _load_comment_check()


def rules_hit(findings) -> set[str]:
    return {f.rule for f in findings}


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """An empty non-git tree: discovery falls back to a filesystem walk, so
    nothing here depends on the repository's own git state."""
    return tmp_path


@pytest.fixture(autouse=True)
def _no_ambient_denylist(monkeypatch):
    """The denylist environment override must not leak in from the shell."""
    monkeypatch.delenv(comment_check.DENYLIST_ENV, raising=False)


# --------------------------------------------------------------------------
# one pinning fixture per rule (mutation resistance)
# --------------------------------------------------------------------------

#: Each entry is a comment and the exact set of rules it must trip. A rule
#: without a row here is a rule that could be deleted unnoticed.
RULE_FIXTURES: tuple[tuple[str, str, str], ...] = (
    ("host-port", "lowercase host", "# reachable on localhost:8791\n"),
    ("host-port", "uppercase host", "# reachable on LOCALHOST:8791\n"),
    ("host-port", "mixed-case host", "# reachable on Localhost:8791\n"),
    ("host-port", "ipv4 loopback", "# reachable on 127.0.0.1:8791\n"),
    ("host-port", "ipv6 loopback", "# reachable on [::1]:8791\n"),
    ("host-port", "docker host alias", "# reachable on host.docker.internal:8791\n"),
    (
        "host-port,tailnet-host",
        "tailnet peer with port",
        "# reachable on shelf-box.ts.net:8791\n",
    ),
    ("port-literal", "flag form", "# start it with --port=8791\n"),
    ("port-literal", "quoted mapping form", '# the compose file sets PORT: "8791"\n'),
    ("private-ip", "rfc1918 10/8", "# the NAS answers at 10.0.0.4\n"),
    ("private-ip", "rfc1918 172.16/12", "# the bridge subnet is 172.20.5.6\n"),
    ("private-ip", "rfc1918 192.168/16", "# the LAN gateway is 192.168.1.1\n"),
    ("private-ip", "cgnat 100.64/10", "# the tailnet peer answers at 100.101.7.9\n"),
    ("private-ip", "link-local 169.254/16", "# metadata service at 169.254.169.254\n"),
    ("tailnet-host", "bare tailnet name", "# published as shelf-box.ts.net\n"),
    ("local-path", "macos home", "# staged under /Users/someone/comics\n"),
    ("local-path", "linux home", "# staged under /home/someone/comics\n"),
    ("local-path", "root home", "# staged under /root/incoming\n"),
    ("local-path", "mounted volume", "# staged under /Volumes/comics-drive\n"),
    ("local-path", "host scratch", "# staged under /tmp/foragerr-scratch\n"),
    ("local-path", "windows profile", "# staged under C:\\Users\\someone\\comics\n"),
    ("local-path", "windows profile lowercased", "# staged under d:\\users\\someone\n"),
    ("local-path", "tilde home", "# staged under ~/comics/incoming\n"),
    ("local-path", "HOME variable", "# staged under $HOME/comics\n"),
    ("local-path", "braced HOME variable", "# staged under ${HOME}/comics\n"),
    ("email", "non-placeholder domain", "# mail someone@internal-host.lan\n"),
    ("provenance", "gate finding phrasing", "# drop the cached row (Codex gate finding).\n"),
)


@pytest.mark.req("FRG-PROC-023")
@pytest.mark.parametrize(
    ("expected", "shape", "comment"),
    RULE_FIXTURES,
    ids=[f"{expected}-{shape}" for expected, shape, _ in RULE_FIXTURES],
)
def test_each_rule_has_a_pinning_positive(tree: Path, expected: str, shape: str, comment: str):
    """Rule 2/3 detection is only as strong as its weakest pattern: every
    documented shape must produce exactly the named rule set, so narrowing a
    pattern cannot pass as a passing suite."""
    (tree / "mod.py").write_text(comment)

    report = comment_check.check(tree)

    assert rules_hit(report.findings) == set(expected.split(",")), [
        str(f) for f in report.findings
    ]


@pytest.mark.req("FRG-PROC-023")
def test_every_rule_is_pinned_by_a_fixture():
    """A rule added without a fixture is a rule with no regression guard."""
    pinned = {name for expected, _shape, _c in RULE_FIXTURES for name in expected.split(",")}
    pinned.add(comment_check.DENYLIST_RULE)  # covered by the denylist tests below

    assert pinned == comment_check.RULE_NAMES


@pytest.mark.req("FRG-PROC-023")
def test_rig_specific_values_are_flagged(tree: Path):
    """A comment carrying a rig host:port, a private address or a home-directory
    path pins one environment — each is a distinct named rule so the report
    tells the author which neutrality rule was broken."""
    (tree / "mod.py").write_text(
        "# reachable on 127.0.0.1:8791 and 192.168.1.10\n"
        "# library lives under /Users/someone/comics\n"
        "VALUE = 1\n"
    )

    report = comment_check.check(tree)

    assert {"host-port", "private-ip", "local-path"} <= rules_hit(report.findings)
    assert all(f.path == "mod.py" for f in report.findings)
    assert {f.line for f in report.findings} == {1, 2}


@pytest.mark.req("FRG-PROC-023")
def test_documented_default_port_is_product_fact(tree: Path):
    """The port foragerr documents as its own default is a product value, not
    an environment value — the host:port rule must not fire on it, or the
    exception mechanism is useless and authors learn to ignore the tool."""
    port = sorted(comment_check.PRODUCT_PORTS)[0]
    (tree / "mod.py").write_text(f"# the app serves on localhost:{port} by default\n")

    report = comment_check.check(tree)

    assert report.findings == []


@pytest.mark.req("FRG-PROC-023")
def test_placeholder_email_domains_are_accepted(tree: Path):
    """RFC 2606 domains and the commit trailer's noreply address exist to be
    committed; flagging them would train authors to ignore the email rule."""
    (tree / "mod.py").write_text(
        "# contact someone@example.com or someone@example.invalid\n"
        "# the trailer address is noreply@anthropic.com\n"
    )

    report = comment_check.check(tree)

    assert report.findings == []


@pytest.mark.req("FRG-PROC-023")
def test_review_provenance_in_a_comment_is_flagged(tree: Path):
    """Rule 1: a comment records the constraint, not which review found it."""
    (tree / "mod.py").write_text("# drop the cached row here (Codex gate finding).\n")

    report = comment_check.check(tree)

    assert rules_hit(report.findings) == {"provenance"}


@pytest.mark.req("FRG-PROC-023")
def test_requirement_id_stating_the_constraint_is_accepted(tree: Path):
    """Rule 1 permits an FRG ID when the ID names the invariant; only
    review-process phrasing is a violation, so an invariant comment citing an
    ID — and prose about the review process in a process document — pass."""
    (tree / "mod.py").write_text(
        '"""Never suppress a single-issue wanted state (FRG-SER-019)."""\n'
        "\n"
        "# A collected edition may contain the issue but does not satisfy it:\n"
        "# no booktype predicate belongs in this query (FRG-SER-019).\n"
    )
    (tree / "notes.md").write_text("The gate review pass covers every angle.\n")

    report = comment_check.check(tree)

    assert report.findings == []


# --------------------------------------------------------------------------
# quote parity: one unbalanced quote must not blind the rest of the file
# --------------------------------------------------------------------------

#: Shapes that leave a quote open at end of line. Each plants the same
#: rig-value comment on the *following* line: carrying quote state across the
#: newline hides it, and with it every later comment in the file.
PARITY_BREAKERS: tuple[tuple[str, str, str], ...] = (
    (
        "toml-literal-block",
        "gitleaks.toml",
        "[[rules]]\nregex = '''\n(?i)secret\\s*=\\s*[a-f0-9]{32,}\n'''\n"
        "# reachable on 127.0.0.1:8791\n",
    ),
    (
        "js-regex-literal",
        "guard.ts",
        "const RX = /href=\"([^\"]+)\"|url\\(\\s*['\"]?https?:/i;\n"
        "// reachable on 127.0.0.1:8791\n",
    ),
    (
        "jsx-apostrophe",
        "Panel.tsx",
        "export const Panel = () => <p>Don't panic</p>;\n"
        "// reachable on 127.0.0.1:8791\n",
    ),
    (
        "shell-heredoc-apostrophe",
        "run.sh",
        "python3 - <<'PY'\n"
        "# the importer's first page must decode\n"
        "print(1)\n"
        "PY\n"
        "# reachable on 127.0.0.1:8791\n",
    ),
    (
        "unterminated-quote",
        "compose.yml",
        'note: "left open on purpose\n# reachable on 127.0.0.1:8791\n',
    ),
)


@pytest.mark.req("FRG-PROC-023")
@pytest.mark.parametrize(
    ("shape", "name", "text"),
    PARITY_BREAKERS,
    ids=[shape for shape, _name, _text in PARITY_BREAKERS],
)
def test_unbalanced_quote_does_not_blind_later_comments(
    tree: Path, shape: str, name: str, text: str
):
    """Quote state SHALL NOT survive a newline. A TOML `'''` delimiter, a JS
    regex literal, a JSX apostrophe, a shell heredoc body or a plainly
    unterminated string each leave one quote open; if that state carried, a
    gate scanner would go silently blind for the remainder of the file — the
    worst possible failure mode for a mechanical check."""
    (tree / name).write_text(text)

    report = comment_check.check(tree)

    assert rules_hit(report.findings) == {"host-port"}, [str(f) for f in report.findings]
    assert [f.path for f in report.findings] == [name]


@pytest.mark.req("FRG-PROC-023")
def test_unbalanced_quote_hiding_a_same_line_comment_is_reported(tree: Path):
    """The residual limit of per-line quote tracking is a comment marker that
    opens *inside* an unbalanced quote on the same line: that comment cannot
    be told apart from string content. The scanner therefore reports the line
    as a misparse rather than passing silently, so the one case it cannot
    decide is visible to the author instead of invisible."""
    (tree / "guard.ts").write_text(
        "const RX = /url\\(\\s*['\"]?https?:/i; // reachable on 127.0.0.1:8791\n"
    )

    report = comment_check.check(tree)

    assert report.findings == []
    assert any("guard.ts" in note and "unbalanced quote" in note for note in report.notes)


@pytest.mark.req("FRG-PROC-023")
def test_multiline_block_comment_lines_are_each_scanned(tree: Path):
    """A `/* */` comment is one token but many authored lines; a rig value on
    its third line is as committed as one on its first."""
    (tree / "guard.ts").write_text(
        "/*\n * The renderer holds one page at a time.\n"
        " * staged under /Users/someone/comics\n */\n"
    )

    report = comment_check.check(tree)

    assert [(f.line, f.rule) for f in report.findings] == [(3, "local-path")]


# --------------------------------------------------------------------------
# local denylist
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-PROC-023")
def test_local_denylist_flags_operator_literals_anywhere(tree: Path):
    """A real collection title cannot be named by a committed pattern, so the
    gitignored local denylist carries it — and is matched against full file
    text, fixture literals included, not just comment text."""
    (tree / "tools").mkdir()
    (tree / "tools" / "comment_check_local_denylist.txt").write_text(
        "# one Python regex per line\nA Real Shelf Title\n"
    )
    (tree / "test_fixtures.py").write_text('SERIES = "A Real Shelf Title (2011)"\n')

    report = comment_check.check(tree)

    assert report.has_denylist is True
    assert [(f.path, f.line, f.rule) for f in report.findings] == [
        ("test_fixtures.py", 1, "local-denylist")
    ]
    assert report.counts["files"] >= 1


@pytest.mark.req("FRG-PROC-023")
def test_local_denylist_covers_files_with_no_comment_syntax(tree: Path):
    """The denylist pass needs no comment extraction, so restricting it to the
    extensions the generic rules understand would exempt exactly the surface
    rule 3 is about: a fixture corpus of release filenames, a JSON fixture, a
    site template."""
    (tree / "tools").mkdir()
    (tree / "tools" / "comment_check_local_denylist.txt").write_text("A Real Shelf Title\n")
    (tree / "realworld_names.txt").write_text("A Real Shelf Title 001 (2011).cbz\n")
    (tree / "fixture.json").write_text('{"series": "A Real Shelf Title"}\n')
    (tree / "page.html").write_text("<h1>A Real Shelf Title</h1>\n")

    report = comment_check.check(tree)

    assert {f.path for f in report.findings} == {
        "realworld_names.txt",
        "fixture.json",
        "page.html",
    }
    assert report.counts["text_files"] >= 3


@pytest.mark.req("FRG-PROC-023")
def test_denylist_never_scans_itself(tree: Path):
    """The denylist holds the literals it hunts for; scanning it would make
    every operator's file report itself and the gate unusable."""
    (tree / "tools").mkdir()
    (tree / "tools" / "comment_check_local_denylist.txt").write_text("A Real Shelf Title\n")

    report = comment_check.check(tree)

    assert report.findings == []


@pytest.mark.req("FRG-PROC-023")
def test_denylist_line_is_a_python_regex(tree: Path):
    """Documented semantics: each line is a Python regex, so an operator can
    write one pattern for a family of titles."""
    (tree / "tools").mkdir()
    (tree / "tools" / "comment_check_local_denylist.txt").write_text(
        r"A Real Shelf Title (?:Vol\.|Volume) \d+" + "\n"
    )
    (tree / "notes.md").write_text("A Real Shelf Title Vol. 3 is on the shelf\n")

    report = comment_check.check(tree)

    assert [(f.path, f.rule) for f in report.findings] == [("notes.md", "local-denylist")]


@pytest.mark.req("FRG-PROC-023")
def test_unparseable_denylist_line_is_a_configuration_error(tree: Path):
    """Falling back to substring matching would let a denylist quietly stop
    meaning what it says; a gate that silently narrows is worse than one that
    refuses to load."""
    (tree / "tools").mkdir()
    (tree / "tools" / "comment_check_local_denylist.txt").write_text("A Real Shelf Title (\n")

    with pytest.raises(comment_check.ConfigError):
        comment_check.check(tree)
    assert comment_check.main([str(tree)]) == 2


@pytest.mark.req("FRG-PROC-023")
def test_empty_denylist_file_counts_as_absent(tree: Path):
    """A denylist holding only comments protects nothing; reporting it as
    present would claim a pass that never ran."""
    (tree / "tools").mkdir()
    (tree / "tools" / "comment_check_local_denylist.txt").write_text(
        "# nothing to hide yet\n\n"
    )
    (tree / "clean.py").write_text("# One writer holds the lock for the whole rename.\n")

    report = comment_check.check(tree)

    assert report.has_denylist is False


@pytest.mark.req("FRG-PROC-023")
def test_denylist_location_is_overridable(tree: Path, tmp_path_factory, monkeypatch, capsys):
    """A worktree or CI job scans with a shared denylist that lives outside
    the tree, so the location is a flag and an environment variable rather
    than a fixed path."""
    shared = tmp_path_factory.mktemp("shared") / "denylist.txt"
    shared.write_text("A Real Shelf Title\n")
    (tree / "notes.md").write_text("A Real Shelf Title (2011)\n")

    assert comment_check.main([str(tree), "--denylist", str(shared)]) == 1

    monkeypatch.setenv(comment_check.DENYLIST_ENV, str(shared))
    assert comment_check.main([str(tree)]) == 1

    monkeypatch.delenv(comment_check.DENYLIST_ENV)
    assert comment_check.main([str(tree)]) == 0
    assert "local-literal pass skipped" in capsys.readouterr().err


@pytest.mark.req("FRG-PROC-023")
def test_absent_local_denylist_does_not_fail_the_gate(tree: Path):
    """A fresh clone and CI have no local denylist: the generic pass still
    runs and decides the exit code, so a missing operator-private file can
    never be the reason a merge gate fails (or passes silently)."""
    (tree / "clean.py").write_text("# One writer holds the lock for the whole rename.\n")
    (tree / "dirty.py").write_text("# staged under /home/someone/incoming\n")

    clean = comment_check.check(tree)
    assert clean.has_denylist is False
    assert rules_hit(clean.findings) == {"local-path"}
    assert comment_check.main([str(tree)]) == 1

    (tree / "dirty.py").unlink()
    report = comment_check.check(tree)

    assert report.has_denylist is False
    assert report.findings == []
    assert comment_check.main([str(tree)]) == 0


# --------------------------------------------------------------------------
# allowlist
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-PROC-023")
def test_allowlist_narrows_to_named_rules(tree: Path):
    """An allowlist entry exempts only the rules it names, so declaring one
    legitimate hit cannot silently license every other violation in the file."""
    (tree / "tools").mkdir()
    (tree / "tools" / "comment_check_allow.txt").write_text(
        "doc.md   local-path    # a portable shell recipe\n"
    )
    (tree / "doc.md").write_text("Run with /tmp/scratch on 127.0.0.1:8791.\n")

    report = comment_check.check(tree)

    assert rules_hit(report.findings) == {"host-port"}


@pytest.mark.req("FRG-PROC-023")
def test_allowlist_rejects_a_wildcard_rule(tree: Path):
    """A blanket exemption also licenses every rule added after it was
    written, which is the one shape a review cannot check."""
    (tree / "tools").mkdir()
    (tree / "tools" / "comment_check_allow.txt").write_text("doc.md   *   # everything\n")
    (tree / "doc.md").write_text("Run on 127.0.0.1:8791.\n")

    with pytest.raises(comment_check.ConfigError):
        comment_check.check(tree)
    assert comment_check.main([str(tree)]) == 2


@pytest.mark.req("FRG-PROC-023")
def test_allowlist_rejects_an_entry_without_rules(tree: Path):
    """A path on its own states no claim, so it cannot be reviewed as one."""
    (tree / "tools").mkdir()
    (tree / "tools" / "comment_check_allow.txt").write_text("doc.md   # no rules named\n")

    with pytest.raises(comment_check.ConfigError):
        comment_check.check(tree)
    assert comment_check.main([str(tree)]) == 2


@pytest.mark.req("FRG-PROC-023")
def test_allowlist_rejects_an_unknown_rule_name(tree: Path):
    """A typo in a rule name would exempt nothing while reading as a granted
    exception — the failure mode is a rule silently still firing, or a rename
    leaving dead exemptions behind."""
    (tree / "tools").mkdir()
    (tree / "tools" / "comment_check_allow.txt").write_text("doc.md   hostport   # typo\n")

    with pytest.raises(comment_check.ConfigError):
        comment_check.check(tree)
    assert comment_check.main([str(tree)]) == 2


@pytest.mark.req("FRG-PROC-023")
def test_unused_allowlist_entry_is_reported(tree: Path):
    """An exemption that no longer suppresses anything is stale licence; it is
    reported so it gets deleted rather than accumulating."""
    (tree / "tools").mkdir()
    (tree / "tools" / "comment_check_allow.txt").write_text(
        "gone.md   local-path   # the file it covered was deleted\n"
    )
    (tree / "clean.py").write_text("# One writer holds the lock for the whole rename.\n")

    report = comment_check.check(tree)

    assert report.findings == []
    assert any("unused entry gone.md" in note for note in report.notes)


@pytest.mark.req("FRG-PROC-023")
def test_repository_allowlist_has_no_unused_entries():
    """Every committed exemption must still be earning its place, or the
    allowlist stops being reviewable."""
    report = comment_check.check(REPO_ROOT)

    assert [note for note in report.notes if "unused entry" in note] == []


# --------------------------------------------------------------------------
# invocation and reporting contract
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-PROC-023")
def test_undecodable_files_are_counted_and_named(tree: Path, capsys):
    """A file the scanner cannot read is a hole in the gate's coverage, so it
    is counted and named rather than dropped — but a binary asset alone is
    not a failure."""
    (tree / "cover.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00binary")
    (tree / "clean.py").write_text("# One writer holds the lock for the whole rename.\n")

    report = comment_check.check(tree)

    assert report.counts["skipped"] == 1
    assert report.skipped == ["cover.png"]
    assert comment_check.main([str(tree)]) == 0
    assert "skipped 1 undecodable file(s): cover.png" in capsys.readouterr().err


@pytest.mark.req("FRG-PROC-023")
def test_nonexistent_root_is_an_invocation_error(tmp_path: Path, capsys):
    """A gate that scans nothing must never report clean: a mistyped root has
    to fail loudly, not exit 0 on an empty file list."""
    assert comment_check.main([str(tmp_path / "no-such-dir")]) == 2

    (tmp_path / "afile.py").write_text("# a file, not a directory\n")
    assert comment_check.main([str(tmp_path / "afile.py")]) == 2
    assert "is not a directory" in capsys.readouterr().err


@pytest.mark.req("FRG-PROC-023")
def test_scanning_zero_files_is_an_invocation_error(tree: Path, capsys):
    """Same failure mode from the other direction: an existing but empty tree
    means the scan never happened."""
    assert comment_check.main([str(tree)]) == 2
    assert "no text files found" in capsys.readouterr().err


@pytest.mark.req("FRG-PROC-023")
def test_walk_fallback_skips_tool_and_agent_state_directories(tree: Path):
    """The non-git fallback walk must not descend into caches or agent-state
    directories: a transcript there holds exactly the values this tool hunts,
    and none of it is committed text."""
    for name in (".venv", "node_modules", ".claude", ".claude-memory"):
        (tree / name).mkdir()
        (tree / name / "notes.py").write_text("# staged under /Users/someone/comics\n")
    (tree / "clean.py").write_text("# One writer holds the lock for the whole rename.\n")

    report = comment_check.check(tree)

    assert report.findings == []
    assert report.counts["files"] == 1


@pytest.mark.req("FRG-PROC-023")
def test_repository_is_clean():
    """The committed tree passes — the retroactive sweep's regression guard."""
    report = comment_check.check(REPO_ROOT)

    assert report.findings == [], "\n".join(str(f) for f in report.findings)
    assert report.counts["files"] > 100
    assert report.counts["text_files"] >= report.counts["files"]


@pytest.mark.req("FRG-PROC-023")
def test_code_is_not_scanned_only_its_non_product_text(tree: Path):
    """Scope is comments/docstrings/test names, never executable code: a
    scanner that rewrote string values used by logic would be unsafe to run
    as a gate."""
    (tree / "mod.py").write_text(
        'STAGING = "/tmp/staging"\n'
        'URL = "http://127.0.0.1:8791/api"\n'
        'LABEL = "gate finding"\n'
    )

    report = comment_check.check(tree)

    assert report.findings == []
