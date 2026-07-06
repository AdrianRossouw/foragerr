"""The single shared archive-safety utility (FRG-SEC-003, FRG-PP-006).

`inspect_archive` is the one entry point every archive-touching path (import
validity/image check now; OPDS page streaming, pack extraction, cover
extraction, and ComicInfo tagging later) uses to open or list a comic archive.
It enforces configurable limits — maximum member count, per-member and total
*declared decompressed* size, and a nesting depth of ``0`` (no archive-in-
archive in M1) — and rejects any member whose name is absolute, contains a
``..``/separator escape, or is a symlink entry, all from the archive's central
directory *before any decompression*. A cbz must additionally contain at least
one image entry (the comic analogue of Sonarr's media-stream check).

The utility never extracts and never raises on hostile input: every rejection
is returned as a typed, logged :class:`ArchiveReport` with ``ok=False`` and a
machine ``reason_code`` plus a user-visible ``reason`` — so the import pipeline
can attach the reason to the candidate file and route corrupt/password archives
to failed-download handling (FRG-PP-006) without a crash or resource blow-up.

CBR (RAR) is validated by magic in M1; full member listing requires the
optional :mod:`rarfile` dependency (+ an ``unrar`` binary) and is applied only
when it imports cleanly — the documented unrar-absent CBR residual (design
decision 4 / Risks). CB7 (7z) is magic-only in M1.
"""

from __future__ import annotations

import logging
import os
import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

#: Image entry extensions that satisfy the cbz "≥1 image" check (FRG-PP-006).
_IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"})

#: Extensions that mark a member as a nested archive (rejected when nesting 0).
_NESTED_ARCHIVE_EXTS = frozenset(
    {".zip", ".cbz", ".rar", ".cbr", ".7z", ".cb7", ".tar", ".cbt", ".gz", ".bz2"}
)

# Container magic prefixes.
_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_RAR_MAGIC = (b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")
_SEVENZIP_MAGIC = (b"7z\xbc\xaf\x27\x1c",)


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    """Configurable archive-safety limits (FRG-SEC-003).

    All caps are on the archive's *declared* central-directory metadata, so a
    declared-size zip bomb is rejected before a single byte is decompressed.
    """

    #: Maximum number of members in the archive.
    max_members: int = 5_000
    #: Maximum declared decompressed size of any single member, in bytes.
    max_member_bytes: int = 256 * 1024 * 1024
    #: Maximum declared decompressed size of the whole archive, in bytes.
    max_total_bytes: int = 4 * 1024 * 1024 * 1024
    #: Maximum nesting depth. M1 forbids archive-in-archive entirely (0).
    max_nesting: int = 0


DEFAULT_ARCHIVE_LIMITS = ArchiveLimits()


@dataclass(frozen=True, slots=True)
class ArchiveReport:
    """Outcome of inspecting an archive.

    On success ``ok`` is ``True`` and the count/size fields are populated. On
    rejection ``ok`` is ``False`` with a machine ``reason_code`` and a
    human-readable ``reason``. ``note`` records a non-fatal caveat (e.g. CBR
    listed by magic only because :mod:`rarfile` is absent).
    """

    ok: bool
    kind: str  # "zip" | "rar" | "7z" | "unknown"
    reason_code: str | None = None
    reason: str | None = None
    member_count: int = 0
    total_uncompressed: int = 0
    image_count: int = 0
    note: str | None = None
    #: Per-member offending name, when a member-name rejection applies.
    offending_member: str | None = field(default=None)


def _reject(
    kind: str, code: str, reason: str, *, path: Path, offending_member: str | None = None
) -> ArchiveReport:
    logger.warning(
        "archive rejected (%s): %s [%s]%s",
        code,
        path,
        reason,
        f" member={offending_member!r}" if offending_member else "",
    )
    return ArchiveReport(
        ok=False,
        kind=kind,
        reason_code=code,
        reason=reason,
        offending_member=offending_member,
    )


def _read_magic(path: Path, n: int = 8) -> bytes:
    with path.open("rb") as handle:
        return handle.read(n)


def _is_image(name: str) -> bool:
    return Path(name).suffix.lower() in _IMAGE_EXTS


def _is_nested_archive(name: str) -> bool:
    return Path(name).suffix.lower() in _NESTED_ARCHIVE_EXTS


def _unsafe_member_name(name: str) -> bool:
    """True if ``name`` is absolute, drive-qualified, or contains a ``..`` /
    separator escape — the zip-slip family, checked before any write/read."""
    if not name:
        return False  # empty/synthetic entry — nothing to escape with
    # Normalize Windows separators so backslash escapes are caught too.
    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        return True  # absolute POSIX path
    if len(name) >= 2 and name[1] == ":" and name[0].isalpha():
        return True  # drive-letter prefix (C:...)
    return any(segment == ".." for segment in normalized.split("/"))


def _is_symlink_member(info: zipfile.ZipInfo) -> bool:
    """True if a zip member is a symlink entry (unix mode in external_attr)."""
    mode = (info.external_attr >> 16) & 0xFFFF
    return bool(mode) and stat.S_ISLNK(mode)


def _detect_kind(magic: bytes) -> str:
    if magic.startswith(_ZIP_MAGIC):
        return "zip"
    if magic.startswith(_RAR_MAGIC):
        return "rar"
    if magic.startswith(_SEVENZIP_MAGIC):
        return "7z"
    return "unknown"


def inspect_archive(
    path: str | os.PathLike[str],
    limits: ArchiveLimits = DEFAULT_ARCHIVE_LIMITS,
    *,
    require_image: bool = True,
) -> ArchiveReport:
    """Inspect a comic archive against ``limits``; never extracts, never raises.

    Returns an :class:`ArchiveReport`. ``require_image`` enforces the cbz "≥1
    image entry" rule for zip containers (FRG-PP-006); it does not apply to the
    magic-only rar/7z paths in M1.
    """
    path = Path(path)
    try:
        magic = _read_magic(path)
    except OSError as exc:
        return _reject(
            "unknown", "unreadable", f"cannot read archive: {exc}", path=path
        )

    kind = _detect_kind(magic)
    if kind == "zip":
        return _inspect_zip(path, limits, require_image=require_image)
    if kind == "rar":
        return _inspect_rar(path, limits)
    if kind == "7z":
        # M1: magic-only container check, no listing (design decision 4).
        return ArchiveReport(
            ok=True,
            kind="7z",
            note="cb7 validated by magic only in M1 (no member listing)",
        )
    return _reject(
        "unknown",
        "bad_magic",
        "magic bytes match no supported comic container (zip/rar/7z) — "
        "likely an HTML error page or corrupt file named as a comic",
        path=path,
    )


def _inspect_zip(
    path: Path, limits: ArchiveLimits, *, require_image: bool
) -> ArchiveReport:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
    except (zipfile.BadZipFile, OSError) as exc:
        return _reject("zip", "corrupt_zip", f"not a valid zip archive: {exc}", path=path)

    member_count = len(infos)
    if member_count > limits.max_members:
        return _reject(
            "zip",
            "too_many_members",
            f"{member_count} members exceeds the cap of {limits.max_members}",
            path=path,
        )

    total = 0
    image_count = 0
    for info in infos:
        name = info.filename
        if _unsafe_member_name(name):
            return _reject(
                "zip",
                "unsafe_member_path",
                "member name is absolute or contains a path-separator/'..' escape",
                path=path,
                offending_member=name,
            )
        if _is_symlink_member(info):
            return _reject(
                "zip", "symlink_member", "member is a symlink entry", path=path,
                offending_member=name,
            )
        if limits.max_nesting <= 0 and _is_nested_archive(name):
            return _reject(
                "zip",
                "nested_archive",
                "member is a nested archive (archive-in-archive forbidden in M1)",
                path=path,
                offending_member=name,
            )
        if info.file_size > limits.max_member_bytes:
            return _reject(
                "zip",
                "member_too_large",
                f"member declares {info.file_size} decompressed bytes, "
                f"over the per-member cap of {limits.max_member_bytes}",
                path=path,
                offending_member=name,
            )
        total += info.file_size
        if total > limits.max_total_bytes:
            return _reject(
                "zip",
                "archive_too_large",
                f"total declared decompressed size exceeds the cap of "
                f"{limits.max_total_bytes} bytes",
                path=path,
            )
        if info.flag_bits & 0x1:
            return _reject(
                "zip",
                "encrypted",
                "archive is password-protected/encrypted — treated as invalid",
                path=path,
                offending_member=name,
            )
        if not name.endswith("/") and _is_image(name):
            image_count += 1

    if require_image and image_count == 0:
        return _reject(
            "zip",
            "no_image_entries",
            "zip contains no image entries — not a comic archive",
            path=path,
        )

    return ArchiveReport(
        ok=True,
        kind="zip",
        member_count=member_count,
        total_uncompressed=total,
        image_count=image_count,
    )


def _inspect_rar(path: Path, limits: ArchiveLimits) -> ArchiveReport:
    """Validate a CBR. RAR magic is already confirmed by the caller.

    When :mod:`rarfile` (and an ``unrar``/``bsdtar`` backend) is importable the
    member list is checked with the same name/size/nesting/count rules; when it
    is not, the archive passes on magic alone — the documented unrar-absent CBR
    residual (design decision 4). No extraction is performed either way.
    """
    try:
        import rarfile  # noqa: PLC0415 — optional dependency, imported lazily
    except ImportError:
        return ArchiveReport(
            ok=True,
            kind="rar",
            note="cbr validated by RAR magic only (rarfile/unrar unavailable) — "
            "members not listed in M1",
        )

    try:
        with rarfile.RarFile(path) as archive:
            infos = archive.infolist()
    except Exception as exc:  # rarfile raises a family of its own error types
        return ArchiveReport(
            ok=True,
            kind="rar",
            note=f"cbr passed on magic; member listing unavailable ({exc})",
        )

    member_count = len(infos)
    if member_count > limits.max_members:
        return _reject(
            "rar",
            "too_many_members",
            f"{member_count} members exceeds the cap of {limits.max_members}",
            path=path,
        )

    total = 0
    image_count = 0
    for info in infos:
        name = info.filename
        if _unsafe_member_name(name):
            return _reject(
                "rar",
                "unsafe_member_path",
                "member name is absolute or contains a path-separator/'..' escape",
                path=path,
                offending_member=name,
            )
        if limits.max_nesting <= 0 and _is_nested_archive(name):
            return _reject(
                "rar",
                "nested_archive",
                "member is a nested archive (archive-in-archive forbidden in M1)",
                path=path,
                offending_member=name,
            )
        size = getattr(info, "file_size", 0) or 0
        if size > limits.max_member_bytes:
            return _reject(
                "rar",
                "member_too_large",
                f"member declares {size} decompressed bytes, over the "
                f"per-member cap of {limits.max_member_bytes}",
                path=path,
                offending_member=name,
            )
        total += size
        if total > limits.max_total_bytes:
            return _reject(
                "rar",
                "archive_too_large",
                f"total declared decompressed size exceeds the cap of "
                f"{limits.max_total_bytes} bytes",
                path=path,
            )
        if _is_image(name):
            image_count += 1

    return ArchiveReport(
        ok=True,
        kind="rar",
        member_count=member_count,
        total_uncompressed=total,
        image_count=image_count,
    )


__all__ = [
    "DEFAULT_ARCHIVE_LIMITS",
    "ArchiveLimits",
    "ArchiveReport",
    "inspect_archive",
]
