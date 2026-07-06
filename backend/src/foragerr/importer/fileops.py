"""Safe file operations for import execution (FRG-PP-007).

Placing an imported file must never leave a partial at its final path and never
delete the source before the destination is verified. The public helpers are
synchronous and filesystem-only (no DB, no parsing) so they run on a worker
thread via the command handler's ``offload`` and are unit-testable in isolation.

- :func:`place_file` — the one file mover. Same-device: a single atomic
  ``os.replace``. Cross-device (rename raises ``EXDEV``): copy to a temp name
  *in the destination directory*, ``fsync``, verify the byte size, atomically
  ``os.replace`` into place, and only then delete the source. A failure at any
  step removes the temp file, so no partial ever appears at the final path.
- :func:`free_space_ok` / :func:`ensure_free_space` — destination free-space
  guard with a configurable margin, checked *before* any bytes are copied.
- :func:`quarantine_file` — move a superseded file under ``<config>/quarantine/
  <date>/`` (the M1 recycle-bin stand-in, FRG-PP-010 / design decision 8).
- :func:`cleanup_empty_dirs` — after a move, remove emptied source directories
  up to (but not including) a stop root (FRG-PP-010).
"""

from __future__ import annotations

import datetime as dt
import errno
import logging
import os
import shutil
import tempfile
from enum import Enum
from pathlib import Path

logger = logging.getLogger("foragerr.importer.fileops")

#: Default free-space safety margin required beyond the file size (FRG-PP-007).
DEFAULT_FREE_SPACE_MARGIN_BYTES = 100 * 1024 * 1024


class TransferMode(Enum):
    """How an imported file is placed (FRG-PP-007). Softlinks are deliberately
    unsupported (they disable tagging and add fragility — design note)."""

    MOVE = "move"
    COPY = "copy"
    HARDLINK = "hardlink"


class NotEnoughSpaceError(OSError):
    """The destination volume lacks the file size plus the configured margin."""


class TransferError(OSError):
    """A transfer failed after cleaning up any partial destination file."""


def free_bytes(path: str | os.PathLike[str]) -> int:
    """Free bytes on the volume backing ``path`` (its nearest existing parent)."""
    probe = Path(path)
    while not probe.exists():
        if probe.parent == probe:
            break
        probe = probe.parent
    return shutil.disk_usage(probe).free


def free_space_ok(
    dest_dir: str | os.PathLike[str],
    needed_bytes: int,
    *,
    margin_bytes: int = DEFAULT_FREE_SPACE_MARGIN_BYTES,
) -> bool:
    """True if ``dest_dir``'s volume has ``needed_bytes + margin_bytes`` free."""
    return free_bytes(dest_dir) >= needed_bytes + margin_bytes


def ensure_free_space(
    dest_dir: str | os.PathLike[str],
    needed_bytes: int,
    *,
    margin_bytes: int = DEFAULT_FREE_SPACE_MARGIN_BYTES,
) -> None:
    """Raise :class:`NotEnoughSpaceError` unless the margin fits (FRG-PP-007)."""
    if not free_space_ok(dest_dir, needed_bytes, margin_bytes=margin_bytes):
        available = free_bytes(dest_dir)
        raise NotEnoughSpaceError(
            f"insufficient free space on {os.fspath(dest_dir)!r}: need "
            f"{needed_bytes} bytes + {margin_bytes} margin, have {available}"
        )


def _copy_verify_delete(src: Path, dst: Path, *, delete_source: bool) -> None:
    """Copy ``src`` → temp in ``dst``'s dir, fsync, verify size, atomic rename.

    No partial file is ever visible at ``dst``: the copy targets a temp name and
    is only promoted with :func:`os.replace` after its size matches the source.
    The source is deleted only on success when ``delete_source`` is set.
    """
    src_size = src.stat().st_size
    fd, tmp_name = tempfile.mkstemp(prefix=".foragerr-import-", dir=str(dst.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as tmp_handle, src.open("rb") as src_handle:
            shutil.copyfileobj(src_handle, tmp_handle, length=1024 * 1024)
            tmp_handle.flush()
            os.fsync(tmp_handle.fileno())
        copied = tmp.stat().st_size
        if copied != src_size:
            raise TransferError(
                f"size mismatch after copy: {copied} != {src_size} for {src}"
            )
        os.replace(tmp, dst)  # atomic promotion into the final path
    except BaseException:
        # Any failure (incl. interruption): remove the partial temp; the final
        # path is untouched and the source is retained.
        with _suppress_missing():
            tmp.unlink()
        raise
    if delete_source:
        with _suppress_missing():
            src.unlink()


class _suppress_missing:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        return exc_type is not None and issubclass(exc_type, FileNotFoundError)


def place_file(
    src: str | os.PathLike[str],
    dst: str | os.PathLike[str],
    *,
    mode: TransferMode = TransferMode.MOVE,
    margin_bytes: int = DEFAULT_FREE_SPACE_MARGIN_BYTES,
) -> Path:
    """Place ``src`` at ``dst`` per ``mode`` (FRG-PP-007). Returns ``dst``.

    The destination parent directory is created first. Free space (file size +
    margin) is checked before any bytes move. MOVE uses an atomic same-device
    rename, falling back to copy-verify-delete across a filesystem boundary.
    COPY keeps the source; HARDLINK links same-device and falls back to COPY
    across devices.
    """
    src_path = Path(src)
    dst_path = Path(dst)
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    ensure_free_space(dst_path.parent, src_path.stat().st_size, margin_bytes=margin_bytes)

    if mode is TransferMode.HARDLINK:
        try:
            os.link(src_path, dst_path)
            return dst_path
        except OSError as exc:
            if exc.errno not in (errno.EXDEV, errno.EPERM, errno.EMLINK):
                raise
            _copy_verify_delete(src_path, dst_path, delete_source=False)
            return dst_path

    if mode is TransferMode.COPY:
        _copy_verify_delete(src_path, dst_path, delete_source=False)
        return dst_path

    # MOVE
    try:
        os.replace(src_path, dst_path)  # atomic, same-device fast path
        return dst_path
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        _copy_verify_delete(src_path, dst_path, delete_source=True)
        return dst_path


def quarantine_file(
    src: str | os.PathLike[str],
    config_dir: str | os.PathLike[str],
    *,
    now: dt.datetime | None = None,
) -> Path:
    """Move a superseded file to ``<config>/quarantine/<date>/`` (FRG-PP-010).

    The M1 stand-in for the M2 recycle bin: the file is moved, never deleted, and
    the returned destination is recorded on the upgrade-replaced history event. A
    name collision within the day's folder is disambiguated with a numeric
    suffix so an earlier quarantined file is never overwritten.
    """
    date = (now or dt.datetime.now(dt.timezone.utc)).date().isoformat()
    src_path = Path(src)
    dest_dir = Path(config_dir) / "quarantine" / date
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src_path.name
    counter = 1
    while dest.exists():
        dest = dest_dir / f"{src_path.stem}.{counter}{src_path.suffix}"
        counter += 1
    # Quarantine is best-effort same-config-volume; fall back across devices.
    try:
        os.replace(src_path, dest)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        _copy_verify_delete(src_path, dest, delete_source=True)
    return dest


def cleanup_empty_dirs(
    start_dir: str | os.PathLike[str],
    stop_root: str | os.PathLike[str],
    *,
    junk_names: frozenset[str] | None = None,
) -> list[str]:
    """Remove emptied directories from ``start_dir`` up to (not incl.) ``stop_root``.

    A directory that still holds a non-junk file survives (FRG-PP-010). ``junk_names``
    (lowercased basenames like ``.ds_store``, ``thumbs.db``) are ignored when
    deciding emptiness — and deleted along with the directory. Returns the list of
    removed directory paths (deepest first). Never touches ``stop_root`` itself.
    """
    junk = junk_names or _DEFAULT_JUNK_NAMES
    stop = Path(stop_root).resolve()
    current = Path(start_dir).resolve()
    removed: list[str] = []
    # Only walk upward while strictly under stop_root.
    while current != stop and stop in current.parents:
        try:
            entries = list(current.iterdir())
        except FileNotFoundError:
            current = current.parent
            continue
        non_junk = [e for e in entries if e.name.lower() not in junk or e.is_dir()]
        # Subdirectories that were themselves emptied are handled by prior
        # iterations; here a surviving subdir or any non-junk file blocks removal.
        if any(e.is_dir() for e in entries) or non_junk:
            break
        for e in entries:  # only junk files remain — remove them with the dir
            with _suppress_missing():
                e.unlink()
        try:
            current.rmdir()
        except OSError:
            break
        removed.append(str(current))
        current = current.parent
    return removed


#: Filenames that never keep a directory alive during move-mode cleanup.
_DEFAULT_JUNK_NAMES: frozenset[str] = frozenset(
    {".ds_store", "thumbs.db", "desktop.ini", ".directory"}
)


__all__ = [
    "DEFAULT_FREE_SPACE_MARGIN_BYTES",
    "NotEnoughSpaceError",
    "TransferError",
    "TransferMode",
    "cleanup_empty_dirs",
    "ensure_free_space",
    "free_bytes",
    "free_space_ok",
    "place_file",
    "quarantine_file",
]
