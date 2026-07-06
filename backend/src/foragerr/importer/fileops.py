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
- :func:`recycle_file` — the M2 first-class recycle bin (FRG-PP-013): move a
  superseded or user-deleted file under ``<recycle_root>/<date>/`` with the same
  collision-safe naming and cross-device fallback, its destination constructed
  through :func:`foragerr.security.paths.safe_join` so an adversarial source name
  can never escape the bin root (design decisions 4-5).
- :func:`dump_file` — move the loser of a duplicate resolution into the
  duplicate-dump folder (FRG-PP-014): the recycle bin's dated-subfolder and
  collision mechanics, but the dump root is never marked as a recycle bin, so
  the retention prune can never touch it.
- :func:`prune_recycle_bin` — housekeeping retention prune of aged recycle-bin
  entries (design decision 7).
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

from foragerr.security.paths import safe_join

logger = logging.getLogger("foragerr.importer.fileops")

#: Default free-space safety margin required beyond the file size (FRG-PP-007).
DEFAULT_FREE_SPACE_MARGIN_BYTES = 100 * 1024 * 1024

#: Marker file :func:`recycle_file` drops at the bin root on first use. Its
#: presence is the sole licence :func:`prune_recycle_bin` needs before it will
#: delete anything — so a housekeeping prune pointed at (say) a library root that
#: was never a recycle bin refuses to touch it, and can never eat series folders
#: (FRG-PP-013, design decision 5).
RECYCLE_BIN_MARKER = ".foragerr-recycle-bin"


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


def _move_into_dated_dir(
    src_path: Path,
    root: str | os.PathLike[str],
    *,
    now: dt.datetime | None = None,
) -> Path:
    """Move ``src_path`` under ``<root>/<date>/`` — the shared dated-subfolder
    mechanics of the recycle bin (FRG-PP-013) and the duplicate-dump folder
    (FRG-PP-014): collision-safe numeric-suffix naming (an earlier entry is
    never overwritten) and the cross-device copy-verify-delete fallback. The
    destination is built via :func:`safe_join` under the resolved root, so a
    source basename engineered to traverse (``..``, absolute) is reduced to a
    single safe segment and can never land outside it (FRG-SEC-004).
    """
    date = (now or dt.datetime.now(dt.timezone.utc)).date().isoformat()
    dest = safe_join(root, date, src_path.name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    counter = 1
    while dest.exists():
        dest = safe_join(root, date, f"{src_path.stem}.{counter}{src_path.suffix}")
        counter += 1
    # Best-effort same-volume rename; fall back across devices, verifying the copy
    # before the source is removed so a root on another mount never loses bytes.
    try:
        os.replace(src_path, dest)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        _copy_verify_delete(src_path, dest, delete_source=True)
    return dest


def recycle_file(
    src: str | os.PathLike[str],
    recycle_root: str | os.PathLike[str],
    *,
    now: dt.datetime | None = None,
) -> Path:
    """Move a superseded/deleted file into the recycle bin (FRG-PP-013).

    The M2 first-class replacement for :func:`quarantine_file`: the file is moved
    (never deleted) under ``<recycle_root>/<date>/`` via the shared
    :func:`_move_into_dated_dir` mechanics (collision-safe naming, cross-device
    fallback, ``safe_join`` confinement — FRG-SEC-004, design decision 5).
    Returns the destination path (recorded on the history event).
    """
    # Stamp the bin so a later housekeeping prune can positively identify this
    # directory as a foragerr recycle bin before it deletes anything (FRG-PP-013).
    _mark_recycle_bin(recycle_root)
    return _move_into_dated_dir(Path(src), recycle_root, now=now)


def dump_file(
    src: str | os.PathLike[str],
    dump_root: str | os.PathLike[str],
    *,
    now: dt.datetime | None = None,
) -> Path:
    """Move the losing file of a duplicate resolution into the dump folder
    (FRG-PP-014).

    Same dated-subfolder + collision-suffix + cross-device mechanics as the
    recycle bin, with one deliberate difference: the dump root is NEVER stamped
    with :data:`RECYCLE_BIN_MARKER`, so :func:`prune_recycle_bin` — which
    refuses to delete anything without that marker — can never prune under the
    dump root. Dumped files are kept until the operator removes them.
    """
    return _move_into_dated_dir(Path(src), dump_root, now=now)


def _mark_recycle_bin(recycle_root: str | os.PathLike[str]) -> None:
    """Drop the :data:`RECYCLE_BIN_MARKER` at the bin root (idempotent)."""
    root = Path(recycle_root)
    root.mkdir(parents=True, exist_ok=True)
    marker = root / RECYCLE_BIN_MARKER
    if not marker.exists():
        marker.touch()


def prune_recycle_bin(
    recycle_root: str | os.PathLike[str],
    retention_days: int,
    *,
    now: dt.datetime | None = None,
) -> int:
    """Permanently remove aged recycle-bin entries older than ``retention_days`` (FRG-PP-013).

    Structurally confined so a misconfigured retention prune can never eat an
    arbitrary directory (design decision 5):

    - it refuses to touch anything unless the bin root carries the
      :data:`RECYCLE_BIN_MARKER` :func:`recycle_file` drops there — a directory
      that was never a foragerr recycle bin (e.g. a library root accidentally
      pointed at) is left completely untouched, with a warning; and
    - it only ever removes **ISO-date-named subdirectories** (``recycle_file``
      always writes under ``<root>/<YYYY-MM-DD>/``), so a loose file or any
      non-date folder in the bin is never a prune target.

    ``retention_days <= 0`` keeps everything (``0`` = keep forever). Returns the
    number of dated folders removed. Never raises on a missing bin.
    """
    if retention_days <= 0:
        return 0
    root = Path(recycle_root)
    if not root.is_dir():
        return 0
    if not (root / RECYCLE_BIN_MARKER).exists():
        logger.warning(
            "recycle prune refused: %s carries no %s marker, so it is not a "
            "foragerr recycle bin — nothing pruned",
            root,
            RECYCLE_BIN_MARKER,
        )
        return 0
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff_date = (now - dt.timedelta(days=retention_days)).date()
    removed = 0
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue  # loose files (incl. the marker) are never prune targets
        try:
            folder_date = dt.date.fromisoformat(entry.name)
        except ValueError:
            continue  # only ISO-date folders recycle_file writes are prunable
        if folder_date < cutoff_date:
            shutil.rmtree(entry)
            removed += 1
    return removed


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
    "RECYCLE_BIN_MARKER",
    "NotEnoughSpaceError",
    "TransferError",
    "TransferMode",
    "cleanup_empty_dirs",
    "dump_file",
    "ensure_free_space",
    "free_bytes",
    "free_space_ok",
    "place_file",
    "prune_recycle_bin",
    "quarantine_file",
    "recycle_file",
]
