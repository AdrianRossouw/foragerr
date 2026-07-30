"""Shared helpers for the read-only-boundary registry invariants (FRG-SER-021).

Uniquely named (like ``opds_support`` / ``flows_support``) so importing it never
shadows the root conftest. The point of this module is the ENUMERATION: the
boundary was bypassed four times by commands reachable through
``POST /api/v1/command``, and per-flow tests cannot notice a command nobody
thought to write a test for. Enumerating the registry and requiring an entry per
command turns "somebody remembered" into "the suite fails until somebody does".

``commands_in_group`` is the enumeration seam; the acquisition half of the
boundary (grab/search commands, which carry no file-mutation exclusivity group)
can enumerate its own membership through the same helper by passing its own
group, or by passing ``None`` to walk the whole registry.
"""

from __future__ import annotations

from pathlib import Path

from foragerr.commands.registry import command_names, command_type


def commands_in_group(exclusivity_group: str | None) -> set[str]:
    """Every registered command name in ``exclusivity_group``.

    ``None`` returns every registered name, for a caller classifying the
    registry on some other property than exclusivity."""
    names = set()
    for name in command_names():
        model = command_type(name)
        if model is None:  # pragma: no cover - command_names() derives from these
            continue
        if exclusivity_group is None or model.exclusivity_group == exclusivity_group:
            names.add(name)
    return names


def snapshot(root: Path) -> dict[str, tuple[bool, int, int, int]]:
    """Every entry under ``root`` -> (is_file, inode, size, mtime_ns).

    The zero-write assertion: comparing this before and after an operation
    catches a moved or renamed file (the relative path key), a re-written one
    (inode/mtime), a truncated one (size), a deleted one (a missing key), and
    anything newly created under the root (an extra key) — including a
    directory rename.
    """
    entries: dict[str, tuple[bool, int, int, int]] = {}
    for path in sorted(root.rglob("*")):
        stat = path.stat()
        entries[str(path.relative_to(root))] = (
            path.is_file(),
            stat.st_ino,
            stat.st_size if path.is_file() else 0,
            stat.st_mtime_ns,
        )
    return entries
