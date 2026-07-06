#!/usr/bin/env python3
"""Verify the SOUP register against the dependency manifests (FRG-PROC-012).

Cross-references, from repository state alone:
  - backend/pyproject.toml               ([project.dependencies] = runtime,
                                           [dependency-groups].dev = tooling)
  - frontend/package.json                (dependencies = runtime,
                                           devDependencies = tooling) -- only if
                                           the file exists; frontend has not
                                           landed yet as of this tool's authoring
  - docs/security/soup-register.md       (runtime + tooling markdown tables)

Exits 0 iff every manifest dependency has a matching register row, every
register row has a matching manifest dependency, and version constraints match
textually. On drift it prints each discrepancy (missing row / orphan row /
constraint mismatch) and exits 1, so it can gate CI/merge like `trace.py`.
"""
from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME_RE = re.compile(r'^([A-Za-z0-9_.\-]+(?:\[[^\]]*\])?)\s*(.*)$')


def _split_dep(entry: str) -> tuple[str, str]:
    """Split a PEP 508-ish dependency string into (name, version constraint)."""
    m = NAME_RE.match(entry.strip())
    if not m:
        return entry.strip(), ''
    return m.group(1).strip(), m.group(2).strip()


def pyproject_deps(root: Path = ROOT):
    """(runtime, tooling) dicts of name -> version constraint from pyproject.toml."""
    path = root / 'backend/pyproject.toml'
    data = tomllib.loads(path.read_text())
    runtime = dict(_split_dep(e) for e in data.get('project', {}).get('dependencies', []))
    tooling = {}
    for group in data.get('dependency-groups', {}).values():
        tooling.update(dict(_split_dep(e) for e in group))
    return runtime, tooling


def package_json_deps(root: Path = ROOT, rel: str = 'frontend/package.json'):
    """(runtime, tooling) dicts of name -> version constraint from a
    package.json, or (None, None) if it does not exist yet."""
    path = root / rel
    if not path.is_file():
        return None, None
    data = json.loads(path.read_text())
    runtime = {k: str(v).strip() for k, v in data.get('dependencies', {}).items()}
    tooling = {k: str(v).strip() for k, v in data.get('devDependencies', {}).items()}
    return runtime, tooling


def register_tables(root: Path = ROOT):
    """Parse docs/security/soup-register.md into
    {(ecosystem, category): {name: constraint}}, ecosystem in {backend, frontend},
    category in {runtime, tools}, keyed off the nearest preceding '## ' header."""
    tables: dict[tuple[str, str], dict[str, str]] = {}
    header = ''
    for line in (root / 'docs/security/soup-register.md').read_text().splitlines():
        if line.startswith('## '):
            header = line[3:].strip()
            continue
        if not line.strip().startswith('|'):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) < 2:
            continue
        name_cell = cells[0].strip('` ').strip()
        if not name_cell or name_cell.lower() == 'name':
            continue
        if set(cells[0]) <= set('-| '):
            continue
        if 'Runtime SOUP items' in header:
            category = 'runtime'
        elif 'Development/test tooling' in header:
            category = 'tools'
        else:
            continue
        if '(frontend)' in header:
            ecosystem = 'frontend'
        elif '(e2e)' in header:
            ecosystem = 'e2e'
        else:
            ecosystem = 'backend'
        constraint = cells[1].strip('` ').strip()
        tables.setdefault((ecosystem, category), {})[name_cell] = constraint
    return tables


def diff(label: str, manifest: dict[str, str], register: dict[str, str]) -> list[str]:
    problems = []
    for name, constraint in sorted(manifest.items()):
        if name not in register:
            problems.append(f'{label}: {name!r} is in the manifest but has no register row')
        elif register[name] != constraint:
            problems.append(
                f'{label}: {name!r} constraint mismatch -- manifest {constraint!r} '
                f'vs register {register[name]!r}'
            )
    for name in sorted(set(register) - set(manifest)):
        problems.append(f'{label}: {name!r} has a register row but is not in the manifest')
    return problems


def check(root: Path = ROOT) -> tuple[list[str], dict[str, int], bool]:
    """Run the full manifest-vs-register comparison rooted at `root`.

    Returns (problems, counts, has_frontend); pure and side-effect free (no
    print/exit), so it is directly callable from tests.
    """
    problems = []
    counts = {}

    backend_runtime, backend_tools = pyproject_deps(root)
    frontend_runtime, frontend_tools = package_json_deps(root)
    tables = register_tables(root)

    reg_backend_runtime = tables.get(('backend', 'runtime'), {})
    reg_backend_tools = tables.get(('backend', 'tools'), {})
    problems += diff('backend runtime', backend_runtime, reg_backend_runtime)
    problems += diff('backend tooling', backend_tools, reg_backend_tools)
    counts['backend runtime'] = len(backend_runtime)
    counts['backend tooling'] = len(backend_tools)

    has_frontend = frontend_runtime is not None
    if has_frontend:
        reg_frontend_runtime = tables.get(('frontend', 'runtime'), {})
        reg_frontend_tools = tables.get(('frontend', 'tools'), {})
        problems += diff('frontend runtime', frontend_runtime, reg_frontend_runtime)
        problems += diff('frontend tooling', frontend_tools, reg_frontend_tools)
        counts['frontend runtime'] = len(frontend_runtime)
        counts['frontend tooling'] = len(frontend_tools)

    e2e_runtime, e2e_tools = package_json_deps(root, 'e2e/package.json')
    if e2e_runtime is not None:
        # The harness is dev tooling by definition: runtime deps are a smell.
        for name in sorted(e2e_runtime):
            problems.append(
                f"e2e: {name!r} is a runtime dependency -- the harness must "
                f"declare devDependencies only"
            )
        problems += diff('e2e tooling', e2e_tools, tables.get(('e2e', 'tools'), {}))
        counts['e2e tooling'] = len(e2e_tools)

    return problems, counts, has_frontend


def main():
    problems, counts, has_frontend = check()
    if not has_frontend:
        print('frontend/package.json not found -- skipping frontend SOUP check')
    print(' · '.join(f'{k}: {v}' for k, v in counts.items()))
    for p in problems:
        print(f'DRIFT: {p}', file=sys.stderr)
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main()
