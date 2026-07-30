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
fixture literal is checked against rules 1–3. Rules 1 and 3 are judgement
calls no regex settles — narration, and whether a title is real — so the
human/agent pass is the primary control and the scanner is the backstop.

### The scanner

`tools/comment_check.py` (stdlib only, `tools/soup_check.py` precedent):

```
python tools/comment_check.py            # 0 = clean, 1 = findings on stderr
```

It extracts the non-product text of each file in scope — Python comments,
docstrings and `test*` names; `//` and `/* */` comments plus
`it`/`test`/`describe` labels in TypeScript; `#` comments in shell, YAML,
TOML and sample configs; the whole body of a committed doc — and applies
pattern-class rules:

| rule | flags |
| --- | --- |
| `host-port` | `host:port` literals on loopback/IP/`host.docker.internal`, except the documented default port |
| `port-literal` | a 4–5 digit port in `port …` / `PORT=…` context, same exception |
| `private-ip` | RFC 1918 addresses (`10.…`, `192.168.…`, `172.16–31.…`) |
| `local-path` | `/Users/<name>`, `/home/<name>`, `/Volumes/…`, `/tmp/…`, `C:\Users\<name>` |
| `email` | email addresses, except `noreply@`/`no-reply@` and RFC 2606 domains (`example.com`, `*.invalid`, `*.test`) |
| `provenance` | review-process phrasing in code comments — `gate finding`, `gate review`, `per review`, `fixed in review`, `reviewer`, `code review`, a reviewer's name |

The rules are *classes*, never lists of specific values: no rig hostname,
port or collection title is committed inside the checker. `provenance`
applies to code comments only — a process document may legitimately discuss
the review process.

### The local denylist

Operator-specific literals that no committed pattern can name — real
collection titles, a rig hostname — go in
`tools/comment_check_local_denylist.txt`, one regex (or plain substring)
per line, `#` for comments. That file is **gitignored**: the values it
holds are exactly the values that must not be committed. When it is
present, its patterns are matched against the full text of every file in
scope, fixture literals included. When it is absent, the tool prints

```
comment_check: no tools/comment_check_local_denylist.txt — local-literal pass skipped (generic pass ran)
```

and exits on the generic pass alone, so a fresh clone and CI stay green
without operator-private data.

### Declaring a legitimate hit

`tools/comment_check_allow.txt` holds committed exceptions, one per line:

```
<path glob>   <rule[,rule]|*>   # why this hit is legitimate
```

An entry is a claim that the matched text is product fact or a deliberate
illustration (this document's own bad examples, the scanner's own
patterns). It is not a way to keep an environment-specific value: if the
honest answer is "that value really is my machine's", the fix is the text,
not the allowlist.
