# foragerr Comment Hygiene Standard

Governed by **FRG-PROC-023**. Enforced in two layers: a comment-hygiene pass
in every review gate's angle checklist, and `tools/comment_check.py`, which
must exit 0 at every merge gate (`docs/process/commit-standard.md`
§Merge-gate checklist).

## Scope

All committed **non-product text**:

- code comments and docstrings (backend, frontend, e2e harness, extension,
  `tools/`, migrations);
- test names and fixture literals;
- sample configs and their comments (Dockerfile, compose files, `*.example`);
- committed docs — `docs/process/`, `docs/research/`, `docs/security/`,
  `docs/traceability/`, `openspec/` proposals and specs, `CLAUDE.md`,
  `CHANGELOG.md`, `.claude/` skills.

Out of scope, because they have their own governing requirements and their
own checks: `README.md` and `docs/manual/` (FRG-PROC-011, FRG-PROC-014,
FRG-PROC-018), and archived proposals under `openspec/changes/archive/` —
an archived proposal is the artefact the owner approved, so it is read-only
evidence rather than living text.

Credential leakage is a different problem with a different control
(FRG-PROC-015, `gitleaks`). This standard is about neutrality and
provenance.

## Rule 1 — a comment states a constraint, not a story

A comment earns its place by saying something the code cannot say itself:
an invariant, an ordering requirement, a reason a tempting simplification
is wrong. It never narrates the next line, and it never records how or
when the code was reviewed — provenance is git's job, and the project's own
review process is not part of the product's source.

Citing a requirement ID is right when the ID *is* the constraint. It is
wrong as a changelog footnote.

```python
# BAD — narration: the code already says this
# increment the retry counter
attempts += 1

# BAD — provenance: which review found it is not the constraint
# skip the cached row here (Codex gate finding, 2026-07-23).

# GOOD — the invariant, and the ID that names it
# Never suppress a single-issue wanted state: a collected edition may
# contain the issue but does not satisfy it (FRG-SER-019).
```

The rewrite of a provenance comment is almost always the constraint that
the review found missing. Keep that; drop the finding.

## Rule 2 — committed text is deployment-neutral

No value that is true of only one environment: no test-rig hostnames or
ports, no container names, no private-network addresses, no local
filesystem paths, no operator usernames or email addresses, no session
dates, no provider account details. Someone reading the repository has a
different machine, and a public repository should not describe the
maintainer's.

Only part of that list has a shape a regex can recognise. Host:port
literals, private/CGNAT/link-local addresses, tailnet names, home-directory
and OS-user paths and email addresses do; container names, bare port
numbers, session dates and provider account details do not — a date is a
date and a name is a name, so a pattern for them would fire far more often
on legitimate text than on a violation. Those are the gate pass's job (and
the local denylist's), and the rule holds for them either way: the scanner
is a backstop, not the definition of the rule.

```python
# BAD — pins one instance
# talk to SABnzbd on 192.168.1.10:8085 (the sab-test container)

# GOOD — states the shape, not the address
# SABnzbd is reached at its configured base URL; a private-network target
# is expected, so the SSRF guard is opt-in per configured host.
```

The one exception is product fact: the port foragerr itself documents as
its default is a documented value, not an environment value, and
`tools/comment_check.py` accepts it (`PRODUCT_PORTS`).

## Rule 3 — examples are synthetic

Identifiers in examples, fixtures and test data are neutral placeholders:
`Example Series #1`, `example.com`, `/comics`, `Example Publisher`. Never a
real series or collection title taken from the operator's library — the
repository is public, and a fixture title is not the place to publish what
somebody owns.

```python
# BAD — a real title from the operator's library as sample data
series = make_series(title="<a real title from the operator's shelves>")

# GOOD
series = make_series(title="Example Series")
```

Real-world names are fine where they are the subject matter rather than
sample data: a metadata provider (`comicvine.gamespot.com`), a publisher
whose naming convention a parser must handle, a project studied in
`docs/research/`.

## Rule 4 — enforcement

### The gate pass

Every review gate's angle checklist includes a comment-hygiene pass over
the branch diff: each added or changed comment, docstring, test name and
fixture literal is checked against rules 1–3.

The gate pass is the **primary** control, and it owns everything the
scanner cannot decide:

- narration (rule 1) — whether a comment says more than the line below it;
- whether a title, name or example is real (rule 3);
- the deployment-neutrality shapes with no distinguishing pattern —
  container names, bare port numbers, session dates, provider account
  details.

### The scanner

`tools/comment_check.py` (stdlib only, `tools/soup_check.py` precedent):

```
python tools/comment_check.py [root] [--denylist PATH]
# 0 = clean, 1 = findings on stderr, 2 = bad invocation or bad config
```

Exit 2 covers the cases where reporting "clean" would be a lie: a root that
is not a directory, a tree with no text files in it at all, a malformed
allowlist entry, an unparseable denylist line.

It extracts the non-product text of each file in scope — Python comments,
docstrings and `test*` names; `//` and `/* */` comments plus
`it`/`test`/`describe` labels in TypeScript; `#` comments in shell, YAML,
TOML and sample configs; the whole body of a committed doc — and applies
pattern-class rules:

| rule | flags |
| --- | --- |
| `host-port` | `host:port` literals on `localhost` (any case), `host.docker.internal`, an IPv4 literal, `[::1]` or a `*.ts.net` peer, except the documented default port |
| `port-literal` | a 4–5 digit port in `port …` / `PORT=…` / `PORT: "…"` context, same exception |
| `private-ip` | RFC 1918 (`10.…`, `192.168.…`, `172.16–31.…`), CGNAT `100.64/10` (tailnet peers), link-local `169.254/16` |
| `tailnet-host` | a bare `*.ts.net` hostname |
| `local-path` | `/Users/<name>`, `/home/<name>`, `/root/<path>`, `/Volumes/…`, `/tmp/…`, `C:\Users\<name>` (any case), `~/<path>`, `$HOME/<path>` |
| `email` | email addresses, except `noreply@`/`no-reply@` and RFC 2606 domains (`example.com`, `*.invalid`, `*.test`) |
| `provenance` | review-process phrasing in code comments — `gate finding`, `gate review`, `per review`, `fixed in review`, `reviewer`, `code review`, `Codex` |
| `local-denylist` | any pattern from the operator's gitignored denylist, matched over full file text (see below) |

Host names are matched case-insensitively (a hostname is
case-insensitive); paths are not, except the Windows drive prefix.

The rules are *classes*, never lists of specific values: no rig hostname,
port or collection title is committed inside the checker. `provenance`
applies to code comments only — a process document may legitimately discuss
the review process.

**What the scanner sees.** The generic rules read only the extracted
non-product text: comments, docstrings, `test*`/`it`/`describe` names, and
the whole body of a committed doc. Executable code and its string values are
never rewritten or flagged, so the tool is safe to run as a gate. The
`local-denylist` rule needs no comment extraction, so it runs over the
**full text of every tracked text file** — fixture corpora, JSON fixtures
and site templates included, which is exactly where rule-3 material lands.
Undecodable/binary files are skipped and reported by count and name.

One structural limit is reported rather than hidden: quote tracking is
per-line, so a comment marker that opens *inside* an unbalanced quote on the
same line (a JS regex literal followed by `//`) cannot be told from string
content. Those lines are printed as `unbalanced quote on line …` notes.
Quote state deliberately does not carry across a newline — a TOML `'''`
delimiter, a JSX apostrophe or a shell heredoc body would otherwise blind
the scanner to every later comment in the file.

### The local denylist

Operator-specific literals that no committed pattern can name — real
collection titles, a rig hostname, a container name — go in
`tools/comment_check_local_denylist.txt`, `#` for comments. That file is
**gitignored**: the values it holds are exactly the values that must not be
committed. `--denylist PATH` or `FORAGERR_COMMENT_DENYLIST` point at a
shared copy, so a worktree or CI job scans with the same list.

**Each non-comment line is a Python regular expression**, matched
case-insensitively — not a substring. A literal containing regex
metacharacters must be escaped — a title such as `Example Series (2011)`
goes in as `Example Series \(2011\)`, and an initialism as `E\.G\.S\.`.
An unparseable line is a configuration error (exit 2), never a silent
fall back to substring matching. A file that exists but holds only comments
is reported as absent, because it protects nothing.

When no denylist is present the tool notes

```
comment_check: no …/comment_check_local_denylist.txt — local-literal pass skipped (generic pass ran)
```

on stderr and exits on the generic pass alone, so a fresh clone and CI stay
green without operator-private data.

### Declaring a legitimate hit

`tools/comment_check_allow.txt` holds committed exceptions, one per line:

```
<path glob>   <rule[,rule]>   # why this hit is legitimate
```

Rule names are **enumerated**, never wildcarded: `*` is rejected as a
configuration error, because a blanket exemption also licenses every rule
added after it was written — the one shape a review cannot check. An entry
with no rule name, or with a rule name the scanner does not know, is also a
configuration error. An entry that suppresses nothing is reported as unused
so it gets deleted instead of accumulating.

An entry is a claim that the matched text is product fact or a deliberate
illustration (this document's own bad examples, the scanner's own
patterns). It is not a way to keep an environment-specific value: if the
honest answer is "that value really is my machine's", the fix is the text,
not the allowlist.
