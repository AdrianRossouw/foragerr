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

CBR (RAR) is a first-class archive kind: when the optional :mod:`rarfile`
dependency (+ an ``unrar``/``bsdtar`` backend binary) is importable the members
are listed and page-streamed through the very same opener seam as ZIP
(FRG-OPDS-016), under the identical resource-limit framework. When the backend
is absent or fails on a specific archive (missing binary, encrypted, broken),
the CBR degrades to the documented magic-only / non-listable residual — no PSE
link, stream 404 — never an error (design decision 4/5 / Risks). CB7 (7z) stays
magic-only.

Archive kind is decided by content (magic bytes), never by file extension, so a
ZIP renamed ``.cbr`` (and a RAR renamed ``.cbz``) routes to the correct opener —
the misnamed-archive class Mylar handles in the wild (FRG-OPDS-016).
"""

from __future__ import annotations

import logging
import os
import re
import stat
import zipfile
import zlib
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

    ``listed`` / ``safe_to_extract`` are DISTINCT from ``ok``. ``ok`` means "this
    passed the M1 import validity check"; a magic-only rar/7z (no member listing
    available) is ``ok=True`` but its members were never vetted for the zip-slip
    / symlink / nesting / size rules. ``listed`` records whether every member was
    actually enumerated, and ``safe_to_extract`` is only ``True`` when the archive
    was both fully listed AND every member passed those rules — so a future
    extractor must gate on ``safe_to_extract``, never on ``ok`` alone, and cannot
    mistake an unlistable container for "members vetted" (FRG-SEC-003).
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
    #: Every member was enumerated from the central directory.
    listed: bool = False
    #: Fully listed AND every member passed the name/symlink/nesting/size vetting
    #: — the only honest signal a future extractor may trust (never ``ok`` alone).
    safe_to_extract: bool = False


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


def is_safe_member_name(name: str) -> bool:
    """Public zip-slip guard: ``True`` when ``name`` is safe to write/read.

    The sanctioned member-name check for callers outside this module (e.g. the
    ComicInfo cbz rewrite's defense-in-depth re-check), so they do not reach into
    the private :func:`_unsafe_member_name`. Simply the negation of it."""
    return not _unsafe_member_name(name)


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
        listed=True,
        safe_to_extract=True,  # every member enumerated + vetted above
    )


def _rar_is_symlink(info: object) -> bool:
    """True if a RAR member is a symlink entry.

    :class:`rarfile.RarInfo` exposes :meth:`is_symlink` (RAR4 unix-mode +
    RAR5 file-redirect records). Guarded with ``getattr`` so an unexpected info
    shape degrades to "not a symlink" rather than raising inside the never-raise
    ``inspect_archive`` contract — the callers still gate on ``safe_to_extract``.
    """
    checker = getattr(info, "is_symlink", None)
    try:
        return bool(checker()) if callable(checker) else False
    except Exception:  # pragma: no cover — defensive; never let a probe raise
        return False


def _inspect_rar(path: Path, limits: ArchiveLimits) -> ArchiveReport:
    """Validate a CBR. RAR magic is already confirmed by the caller.

    When :mod:`rarfile` (and an ``unrar``/``bsdtar`` backend) is importable the
    member list is checked with the SAME name/symlink/nesting/size/count rules as
    ZIP (FRG-OPDS-016), so a fully-listed CBR is ``safe_to_extract`` and streams
    through the shared page path. When the backend is absent, the archive is
    encrypted (header- or per-file), or the listing otherwise fails, the archive
    passes on magic alone (``listed=False`` → non-listable, no PSE) — the
    documented unrar-absent / degrade path (design decisions 4/5). No extraction
    is performed either way (listing reads headers only).
    """
    try:
        import rarfile  # noqa: PLC0415 — optional dependency, imported lazily
    except ImportError:
        return ArchiveReport(
            ok=True,
            kind="rar",
            note="cbr validated by RAR magic only (rarfile/unrar unavailable) — "
            "members not listed",
        )

    try:
        with rarfile.RarFile(path) as archive:
            # Encrypted CBRs (header- or per-file-encrypted) degrade to the
            # non-listable residual, exactly like a missing backend: no PSE, and
            # the stream endpoint 404s. We never prompt for or hold a password.
            if archive.needs_password():
                return ArchiveReport(
                    ok=True,
                    kind="rar",
                    note="cbr is encrypted — passed on magic, members not listed",
                )
            infos = archive.infolist()
    except Exception as exc:  # rarfile raises a family of its own error types
        return ArchiveReport(
            ok=True,
            kind="rar",
            note=f"cbr passed on magic; member listing unavailable ({exc})",
        )

    if not infos:
        # rarfile accepts a bare RAR *signature* with no parsable block body as a
        # valid empty archive. A comic RAR always has members, so a zero-member
        # listing is indistinguishable from a signature-only stub / truncated
        # container — degrade to the magic-only, non-listable residual (no PSE),
        # exactly like the unrar-absent path, rather than advertising an empty
        # streamable archive.
        return ArchiveReport(
            ok=True,
            kind="rar",
            note="cbr has no listable members — passed on magic only",
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
        if _rar_is_symlink(info):
            return _reject(
                "rar", "symlink_member", "member is a symlink entry", path=path,
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
        listed=True,
        safe_to_extract=True,  # rarfile enumerated + vetted every member
    )


# --- OPDS page streaming: ordered image-member listing + safe reader ---------
# (FRG-OPDS-010, FRG-OPDS-012). These sit on top of ``inspect_archive`` and are
# the archive half of the new OPDS page/cover surface. They never extract to
# disk: listing reads only the central directory; the reader loads one vetted
# member into memory under a byte cap. Both gate on ``safe_to_extract`` (never
# ``ok``) — the archive module's documented rule for any extractor.


class ArchiveMemberError(Exception):
    """A single archive member could not be read safely (FRG-OPDS-012).

    Raised by :func:`read_image_member` on a member-name violation (zip-slip /
    absolute / symlink), a declared size over the caller's byte cap (checked
    BEFORE any decompression), an absent member, or archive corruption caught
    during the read. The caller degrades to a bounded 4xx/5xx, never a crash or
    a memory blow-up.
    """


def natural_sort_key(name: str) -> tuple[tuple[int, object], ...]:
    """Numeric-aware sort key so ``1.jpg, 2.jpg, 10.jpg`` sort in that order.

    Splits the name into alternating non-digit / digit runs; digit runs compare
    as integers (so zero-padding is irrelevant — ``02`` and ``2`` collate the
    same and both precede ``10``), non-digit runs compare case-insensitively.
    Each element is a ``(rank, value)`` tuple whose first slot keeps ints and
    strings from ever being compared against each other.
    """
    key: list[tuple[int, object]] = []
    for chunk in re.split(r"(\d+)", name):
        if chunk.isdigit():
            key.append((0, int(chunk)))
        else:
            key.append((1, chunk.lower()))
    return tuple(key)


#: A normalized archive-member record produced by the per-format enumerators
#: (:func:`_zip_entries` / :func:`_rar_entries`) so the image-member filter is
#: identical across backends. ``(name, is_dir, is_symlink)``.
_MemberEntry = tuple[str, bool, bool]


def _zip_entries(path: str | os.PathLike[str]) -> list[_MemberEntry] | None:
    """Enumerate a ZIP's members as normalized ``(name, is_dir, is_symlink)``
    records, or ``None`` if the container cannot be opened. Reads only the
    central directory — no member is decompressed."""
    try:
        with zipfile.ZipFile(path) as archive:
            return [
                (info.filename, info.filename.endswith("/"), _is_symlink_member(info))
                for info in archive.infolist()
            ]
    except (zipfile.BadZipFile, OSError):
        return None


def _rar_entries(path: str | os.PathLike[str]) -> list[_MemberEntry] | None:
    """Enumerate a RAR's members as normalized ``(name, is_dir, is_symlink)``
    records, or ``None`` when the ``rarfile`` backend is unavailable or the
    listing fails. Reads only headers via ``rarfile`` — no member is extracted."""
    try:
        import rarfile  # noqa: PLC0415 — optional dependency, imported lazily
    except ImportError:
        return None
    try:
        with rarfile.RarFile(path) as archive:
            return [
                (info.filename, info.isdir(), _rar_is_symlink(info))
                for info in archive.infolist()
            ]
    except Exception:  # rarfile's own error family (broken/encrypted/backend)
        return None


def _enumerate_members(
    path: str | os.PathLike[str], kind: str
) -> list[_MemberEntry] | None:
    """Dispatch member enumeration to the backend for ``kind`` (the magic-detected
    container kind from :class:`ArchiveReport`). The single archive-opener seam
    (FRG-OPDS-016): ZIP and RAR share one downstream filter; extension never
    decides the opener, so a misnamed archive routes by content."""
    if kind == "zip":
        return _zip_entries(path)
    if kind == "rar":
        return _rar_entries(path)
    return None  # 7z / unknown: not page-streamable


def list_image_members(
    path: str | os.PathLike[str],
    limits: ArchiveLimits = DEFAULT_ARCHIVE_LIMITS,
) -> list[str] | None:
    """Ordered image members of a listable archive, or ``None`` (FRG-OPDS-010,
    FRG-OPDS-016).

    Returns the archive's image members (extensions in :data:`_IMAGE_EXTS`) in
    :func:`natural_sort_key` order, EXCLUDING directory entries, symlink members,
    ``..``/absolute member names, non-image members and ``ComicInfo.xml``. This
    is exactly the OPDS "page" set — its length is the PSE ``pse:count`` and its
    indexes address stream pages. ZIP (CBZ) and RAR (CBR) are served identically
    through the shared opener seam; the container kind is chosen by content, so a
    ZIP renamed ``.cbr`` (or the reverse) lists correctly.

    Returns ``None`` when the archive is not safely listable: gated on the
    :class:`ArchiveReport` ``safe_to_extract`` flag (never ``ok``), so a CBR with
    :mod:`rarfile`/``unrar`` absent, an encrypted/broken RAR, an oversized/hostile
    archive, a 7z/unknown container, or a corrupt file all degrade to "no pages".
    A listable archive with zero image members returns an empty list (listable, no
    pages) — distinct from ``None`` (not listable).

    ``limits.max_members`` (and the size ceilings) are enforced by
    :func:`inspect_archive`, which sets ``safe_to_extract=False`` when a cap is
    exceeded — for both ZIP and RAR.
    """
    report = inspect_archive(path, limits, require_image=False)
    if not report.safe_to_extract:
        return None
    entries = _enumerate_members(path, report.kind)
    if entries is None:
        # ``safe_to_extract`` but the opener could not re-enumerate (e.g. the RAR
        # backend vanished between inspect and list, or a container the reader
        # cannot serve) — degrade to "no pages" (design §5).
        return None

    members: list[str] = []
    for name, is_dir, is_symlink in entries:
        if is_dir:
            continue  # directory entry
        if is_symlink:
            continue
        if _unsafe_member_name(name):
            continue
        if Path(name).name.lower() == "comicinfo.xml":
            continue
        if not _is_image(name):
            continue
        members.append(name)

    members.sort(key=natural_sort_key)
    return members


def read_image_member(
    path: str | os.PathLike[str], member: str, *, max_bytes: int
) -> bytes:
    """Read one image member into memory under a byte cap (FRG-OPDS-012,
    FRG-OPDS-016).

    Defense-in-depth for the OPDS page path: re-checks the member name for the
    zip-slip family (absolute / ``..`` / drive-qualified) even though
    :func:`list_image_members` already filtered it, then dispatches to the backend
    for the archive's *content* kind (magic bytes, never the extension) — so a
    misnamed archive reads via the correct opener. Both backends reject a symlink
    member and check the member's DECLARED decompressed size against ``max_bytes``
    BEFORE reading — so a declared-oversize member is refused pre-decompression.
    The RAR backend reads a single member through ``rarfile`` (an ``unrar``
    subprocess), never a full-archive extraction. Mirrors the byte-cap-before-read
    idiom in :func:`foragerr.metadata.comicinfo.read_embedded_metadata`.

    Raises :class:`ArchiveMemberError` on any violation, an absent member, an
    unavailable/failed backend, or archive corruption caught during the read;
    never returns partial/oversized bytes.
    """
    if not is_safe_member_name(member):
        raise ArchiveMemberError(
            f"unsafe member name refused (zip-slip guard): {member!r}"
        )
    kind = _detect_kind(_read_magic(Path(path)))
    if kind == "zip":
        return _zip_read_member(path, member, max_bytes=max_bytes)
    if kind == "rar":
        return _rar_read_member(path, member, max_bytes=max_bytes)
    raise ArchiveMemberError(
        f"cannot read member {member!r}: {path} is not a supported archive "
        f"(magic did not match zip or rar)"
    )


def _zip_read_member(
    path: str | os.PathLike[str], member: str, *, max_bytes: int
) -> bytes:
    """Single-member ZIP read under the declared-size-before-read byte cap."""
    try:
        with zipfile.ZipFile(path) as archive:
            try:
                info = archive.getinfo(member)
            except KeyError as exc:
                raise ArchiveMemberError(f"member not found: {member!r}") from exc
            if _is_symlink_member(info):
                raise ArchiveMemberError(f"member is a symlink entry: {member!r}")
            if info.file_size > max_bytes:
                raise ArchiveMemberError(
                    f"member {member!r} declares {info.file_size} bytes, over the "
                    f"per-page cap of {max_bytes}"
                )
            return archive.read(member)
    except (OSError, zipfile.BadZipFile, NotImplementedError, zlib.error) as exc:
        # Archive passed listing but this member could not be read: an IO error /
        # concurrent change (OSError, BadZipFile), an unsupported compression
        # method (NotImplementedError), or a corrupt deflate stream (zlib.error).
        raise ArchiveMemberError(
            f"could not read member {member!r} from {path}: {exc}"
        ) from exc


def _rar_read_member(
    path: str | os.PathLike[str], member: str, *, max_bytes: int
) -> bytes:
    """Single-member RAR read under the declared-size-before-read byte cap.

    ``rarfile.RarFile.read`` extracts exactly one member (spawning ``unrar`` for
    that member) — never the whole archive to disk. The declared
    ``RarInfo.file_size`` is checked BEFORE the read so a declared-oversize page is
    refused pre-decompression, mirroring the ZIP path. A missing backend, an
    absent member, a symlink member, an encrypted member, or any ``rarfile`` error
    becomes an :class:`ArchiveMemberError` so the caller degrades to a bounded 4xx/
    5xx (design §5) — never a crash."""
    try:
        import rarfile  # noqa: PLC0415 — optional dependency, imported lazily
    except ImportError as exc:
        raise ArchiveMemberError(
            f"cannot read member {member!r}: RAR backend (rarfile/unrar) unavailable"
        ) from exc
    try:
        with rarfile.RarFile(path) as archive:
            try:
                info = archive.getinfo(member)
            except rarfile.NoRarEntry as exc:
                raise ArchiveMemberError(f"member not found: {member!r}") from exc
            if _rar_is_symlink(info):
                raise ArchiveMemberError(f"member is a symlink entry: {member!r}")
            size = getattr(info, "file_size", 0) or 0
            if size > max_bytes:
                raise ArchiveMemberError(
                    f"member {member!r} declares {size} bytes, over the "
                    f"per-page cap of {max_bytes}"
                )
            return archive.read(member)
    except rarfile.Error as exc:
        # rarfile's whole error family (corrupt/encrypted/backend failure). A
        # separate clause from ArchiveMemberError so our own typed rejections
        # (size/symlink/missing above) propagate unchanged.
        raise ArchiveMemberError(
            f"could not read member {member!r} from {path}: {exc}"
        ) from exc
    except OSError as exc:
        raise ArchiveMemberError(
            f"could not read member {member!r} from {path}: {exc}"
        ) from exc


__all__ = [
    "DEFAULT_ARCHIVE_LIMITS",
    "ArchiveLimits",
    "ArchiveMemberError",
    "ArchiveReport",
    "inspect_archive",
    "is_safe_member_name",
    "list_image_members",
    "natural_sort_key",
    "read_image_member",
]
