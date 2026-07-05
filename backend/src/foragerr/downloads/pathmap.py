"""Remote path mapping: rewrite client-reported paths for local import (FRG-DL-005).

A download client (SABnzbd, or a DDL runner) may report a completed download's
path in the client's own filesystem namespace — a different container mount or a
different host. Per-client ``remote_path → local_path`` prefix rewrites make
those paths importable. The load-bearing property (FRG-DL-005 scenario 2): a
completed path that is *foreign* (a different-OS shape, or a prefix with no
matching mapping when mappings are configured for the client) is surfaced with a
"check remote path mapping" WARNING rather than a silent import failure.

Pure/deterministic and filesystem-free so it is unit-testable: "foreign" is
judged from the path shape and the presence of configured mappings, never from
probing the local filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The warning surfaced (as a ClientItem ``warning`` status + reason) when a
#: foreign completed path has no matching mapping (FRG-DL-005 scenario 2).
CHECK_MAPPING_WARNING = "check remote path mapping"


@dataclass(frozen=True, slots=True)
class RemotePathMapping:
    """One remote→local prefix rewrite for a client running on ``host``."""

    host: str
    remote_prefix: str
    local_prefix: str


@dataclass(frozen=True, slots=True)
class MappingResult:
    """The outcome of applying mappings to one completed path.

    ``path`` is the (possibly rewritten) path to import from; ``warning`` is
    non-``None`` (:data:`CHECK_MAPPING_WARNING`) when the path is foreign and
    unmapped, so the caller can flag the item ``warning`` instead of failing it.
    """

    path: str
    warning: str | None


def _looks_windows(path: str) -> bool:
    """True for a Windows-shaped path (drive letter or backslash separators)."""
    if "\\" in path:
        return True
    return len(path) >= 2 and path[0].isalpha() and path[1] == ":"


def _normalize_prefix(prefix: str) -> str:
    """Trailing-separator-insensitive prefix (so ``/dl`` matches ``/dl/x``)."""
    return prefix.rstrip("/\\")


def apply_mappings(
    output_path: str, mappings: list[RemotePathMapping]
) -> MappingResult:
    """Rewrite ``output_path`` through the first matching mapping (FRG-DL-005).

    - A mapping whose ``remote_prefix`` is a prefix of ``output_path`` rewrites
      it to the ``local_prefix`` and returns no warning.
    - No matching mapping and a *foreign* path (Windows-shaped on this POSIX
      host, or any path when mappings are configured yet none match) returns the
      path unchanged with :data:`CHECK_MAPPING_WARNING`.
    - No mappings configured and a plain local-looking path returns it unchanged
      with no warning (the single-host default deployment).
    """
    for mapping in mappings:
        remote = _normalize_prefix(mapping.remote_prefix)
        if output_path == remote or output_path.startswith(remote + "/") or (
            "\\" in mapping.remote_prefix
            and (
                output_path == remote or output_path.startswith(remote + "\\")
            )
        ):
            suffix = output_path[len(remote):]
            local = _normalize_prefix(mapping.local_prefix)
            # Normalize the joined separator to POSIX for the local namespace.
            suffix = suffix.replace("\\", "/")
            rewritten = local + suffix if suffix else local
            return MappingResult(path=rewritten, warning=None)

    # No mapping matched. Decide whether this is a foreign, unmapped path.
    if _looks_windows(output_path) or mappings:
        return MappingResult(path=output_path, warning=CHECK_MAPPING_WARNING)
    return MappingResult(path=output_path, warning=None)


__all__ = [
    "CHECK_MAPPING_WARNING",
    "MappingResult",
    "RemotePathMapping",
    "apply_mappings",
]
