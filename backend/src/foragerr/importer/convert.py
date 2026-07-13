"""Opt-in CBR→CBZ conversion with verify-before-discard (FRG-PP-018).

The format-shift half of cbr-support phase 2. A CBR (RAR) is rewritten as a CBZ
(ZIP) — at import time behind the off-by-default policy flag
(:attr:`ImportContext.convert_cbr_to_cbz`), or on demand per issue/series (which
never reads the flag). Either way the contract is identical (FRG-PP-018):

    build → verify → promote → swap the ``issue_files`` row → discard the original

- **Reuse the archive seam, never open archives our own way.** The source CBR is
  read through the phase-1 opener seam only: :func:`_enumerate_members` lists the
  members and :func:`read_image_member` streams each one (an ``unrar`` subprocess
  per member, never a full-archive extraction to disk), under the same
  member-name / symlink / declared-size guards ZIP gets.
- **Verify BEFORE the original is discarded.** The produced CBZ is reopened and
  its member count is checked against the source listing (a truncated write is
  caught), and its final image page is decoded through the hardened
  :func:`~foragerr.security.images.render_page` (an undecodable page fails the
  conversion). Only then is the original CBR removed.
- **Atomic, recoverable ordering.** The CBZ is written to a hidden temp beside
  the destination (``mkstemp`` there → an in-directory :func:`os.replace`
  promotion), mirroring :func:`foragerr.metadata.comicinfo.tag_cbz`. The row swap
  (path/size/page-count) and the ``converted`` history event land in the SAME
  transaction; the original CBR is removed last. A failure at any point before
  the row swap keeps the original CBR as the imported file and records a
  ``convert_failed`` warning — the surrounding import (or on-demand run) still
  succeeds; the file is never lost.

:func:`apply_conversion` is the single async entry point both callers use; the
build/verify/promote primitives are pure filesystem work (no DB) so they run
through the pipeline/flow ``offload`` seam off the event loop.
"""

from __future__ import annotations

import logging
import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.importer import history
from foragerr.library.models import IssueFileRow
from foragerr.security.archives import (
    DEFAULT_ARCHIVE_LIMITS,
    ArchiveLimits,
    ArchiveMemberError,
    _detect_kind,
    _enumerate_members,
    _read_magic,
    list_image_members,
    read_image_member,
)
from foragerr.security.images import ImageRenderError, render_page

logger = logging.getLogger("foragerr.importer.convert")

#: Pixel ceiling for the verification decode of the final page — the global
#: Pillow decompression-bomb backstop (:data:`foragerr.security.images`). The
#: verify only needs to prove the last page decodes, not render it.
_VERIFY_MAX_PIXELS = 64_000_000

#: Prefix for the hidden temp CBZ written beside the destination before its
#: atomic promotion (mirrors ``.foragerr-comicinfo-`` / ``.foragerr-import-``).
_TEMP_PREFIX = ".foragerr-convert-"


class ConvertError(Exception):
    """A CBR→CBZ conversion could not be completed safely (FRG-PP-018).

    Raised by :func:`build_verified_cbz` when the source cannot be listed, a
    member cannot be read, the produced CBZ's member count does not match the
    source listing, or the final page does not decode as an image. The temp CBZ
    is always unlinked before this propagates, so the destination is untouched
    and the original CBR is kept.
    """


@dataclass(frozen=True, slots=True)
class BuiltCbz:
    """A verified temp CBZ awaiting promotion (FRG-PP-018)."""

    temp_path: Path
    size: int
    page_count: int


def is_cbr_file(path: str | os.PathLike[str]) -> bool:
    """True when ``path`` is a RAR archive by MAGIC (never by extension).

    The convert step is a no-op for anything that is not RAR-magic — a genuine
    CBZ (ZIP), a 7z, or a misnamed file — so an on-demand per-series run skips
    already-CBZ files without an event (FRG-PP-018)."""
    try:
        return _detect_kind(_read_magic(Path(path))) == "rar"
    except OSError:
        return False


def cbz_path_for(cbr_path: str | os.PathLike[str]) -> Path:
    """The destination CBZ path: the source stem with a ``.cbz`` extension.

    Only the extension changes — the stem is preserved, so conversion never
    renames beyond the format shift (renaming stays governed by
    ``rename_enabled``, applied at import placement time, FRG-PP-018)."""
    return Path(cbr_path).with_suffix(".cbz")


def build_verified_cbz(
    source_cbr: str | os.PathLike[str],
    final_cbz: str | os.PathLike[str],
    *,
    limits: ArchiveLimits = DEFAULT_ARCHIVE_LIMITS,
) -> BuiltCbz:
    """Write a verified temp CBZ beside ``final_cbz`` from ``source_cbr``.

    Enumerates the source members through the archive seam, streams each into a
    hidden temp ZIP in ``final_cbz``'s directory, then VERIFIES the temp before
    returning: the reopened member count must equal the source listing (a
    truncated write is caught) and the final image member must decode. Returns a
    :class:`BuiltCbz` (temp path + size + image page count); the caller promotes
    it. Raises :class:`ConvertError` on any failure, having unlinked the temp —
    so the destination is never left with a partial CBZ and the original CBR is
    untouched. Pure filesystem work (no DB); run it through the ``offload`` seam.
    """
    source = Path(source_cbr)
    dest = Path(final_cbz)
    kind = _detect_kind(_read_magic(source))
    entries = _enumerate_members(source, kind)
    if not entries:
        raise ConvertError(
            f"source archive {source} is not listable (backend absent, "
            f"encrypted, or empty) — cannot convert"
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=_TEMP_PREFIX, dir=str(dest.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        expected = 0
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
            for name, is_dir, is_symlink in entries:
                if is_symlink:
                    # A safe-to-extract RAR has none; refuse defensively rather
                    # than copy a symlink member into the CBZ.
                    raise ConvertError(
                        f"refusing to convert: symlink member {name!r} in {source}"
                    )
                if is_dir:
                    dst.writestr(name, b"")
                    expected += 1
                    continue
                # Read one member through the seam (magic-dispatched to the RAR
                # backend, member-name + declared-size guarded); a violation or a
                # backend failure becomes a ConvertError below.
                data = read_image_member(source, name, max_bytes=limits.max_member_bytes)
                dst.writestr(name, data)
                expected += 1

        # --- verify BEFORE the caller discards the original (FRG-PP-018) -------
        with zipfile.ZipFile(tmp) as check:
            produced = len(check.namelist())
        if produced != expected:
            raise ConvertError(
                f"produced CBZ has {produced} members, expected {expected} from "
                f"the source listing (truncated write)"
            )
        images = list_image_members(tmp, limits)
        if not images:
            raise ConvertError(
                "produced CBZ has no listable image pages — refusing to convert"
            )
        # The final page must decode as an image (the readable-last-page check).
        final_bytes = read_image_member(tmp, images[-1], max_bytes=limits.max_member_bytes)
        render_page(final_bytes, max_width=None, max_pixels=_VERIFY_MAX_PIXELS)

        return BuiltCbz(temp_path=tmp, size=tmp.stat().st_size, page_count=len(images))
    except (ConvertError, ArchiveMemberError, ImageRenderError, OSError, zipfile.BadZipFile) as exc:
        _unlink_quiet(tmp)
        if isinstance(exc, ConvertError):
            raise
        raise ConvertError(f"CBR→CBZ conversion of {source} failed: {exc}") from exc
    except BaseException:
        # Cancellation/shutdown mid-build: clean the temp, then let it propagate.
        _unlink_quiet(tmp)
        raise


def promote_cbz(temp_path: str | os.PathLike[str], final_cbz: str | os.PathLike[str]) -> Path:
    """Atomically promote the verified temp CBZ onto ``final_cbz`` (FRG-PP-018).

    ``fsync`` the temp, ``os.replace`` it into place (a reader never sees a
    half-written CBZ), then best-effort ``fsync`` the directory so the rename
    survives a crash right after it — mirroring ``tag_cbz``'s promotion. On any
    failure the temp is unlinked so no stray temp is left behind. Filesystem
    work; run it through the ``offload`` seam."""
    tmp = Path(temp_path)
    dest = Path(final_cbz)
    try:
        with open(tmp, "rb+") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, dest)
    except BaseException:
        _unlink_quiet(tmp)
        raise
    _fsync_dir_quiet(dest.parent)
    return dest


async def apply_conversion(
    session: AsyncSession,
    *,
    issue_file_id: int,
    source_path: str,
    series_id: int | None,
    issue_id: int | None,
    now,
    source: str | None = None,
    download_id: str | None = None,
    source_title: str | None = None,
    offload=None,
    limits: ArchiveLimits = DEFAULT_ARCHIVE_LIMITS,
) -> str | None:
    """Convert one CBR issue-file to CBZ under verify-before-discard (FRG-PP-018).

    The single entry point shared by the convert-at-import step and the on-demand
    per-issue/per-series flow. Steps:

    1. **No-op** when ``source_path`` is not RAR-magic (an already-CBZ / non-CBR
       file) — returns ``None`` with no event (the on-demand skip).
    2. **Build + verify** a temp CBZ beside the destination (member count matches
       the source listing; the final page decodes). A failure records a
       ``convert_failed`` warning event, keeps the original CBR, returns ``None``.
    3. **Promote + swap.** The temp is atomically promoted onto the ``.cbz``
       destination, the ``issue_files`` row swaps path/size/page-count and a
       ``converted`` event is recorded IN THIS SESSION, and only then is the
       original CBR removed. Returns the new CBZ path.

    All DB writes land in the caller's transaction; all filesystem work runs
    through ``offload`` (``None`` runs inline). Never raises: a promote/DB failure
    after the build is caught and recorded as ``convert_failed`` so the caller's
    surrounding operation still succeeds and the original file is never lost.
    """

    async def _run_fs(func, *args, **kwargs):
        if offload is not None:
            return await offload(func, *args, **kwargs)
        return func(*args, **kwargs)

    if not await _run_fs(is_cbr_file, source_path):
        return None  # non-CBR: no-op, no event (FRG-PP-018 on-demand skip)

    dest = cbz_path_for(source_path)
    if dest.exists() and not _same_physical_file(dest, source_path):
        # A different file already occupies the .cbz target — never clobber it.
        _record_failed(
            session,
            series_id=series_id,
            issue_id=issue_id,
            source=source,
            download_id=download_id,
            source_title=source_title,
            now=now,
            path=source_path,
            error=f"destination {dest} already exists",
        )
        return None

    # 1. Build + verify (no original touched, temp is hidden beside the dest).
    try:
        built: BuiltCbz = await _run_fs(
            build_verified_cbz, source_path, str(dest), limits=limits
        )
    except ConvertError as exc:
        logger.warning("convert: %s kept (verification failed): %s", source_path, exc)
        _record_failed(
            session,
            series_id=series_id,
            issue_id=issue_id,
            source=source,
            download_id=download_id,
            source_title=source_title,
            now=now,
            path=source_path,
            error=str(exc),
        )
        return None

    # 2. Promote the verified temp onto the .cbz destination.
    try:
        await _run_fs(promote_cbz, str(built.temp_path), str(dest))
    except Exception as exc:  # noqa: BLE001 — a promote failure keeps the original
        logger.warning("convert: promotion of %s failed; original kept: %s", dest, exc)
        _record_failed(
            session,
            series_id=series_id,
            issue_id=issue_id,
            source=source,
            download_id=download_id,
            source_title=source_title,
            now=now,
            path=source_path,
            error=f"promotion failed: {exc}",
        )
        return None

    # 3. From here the verified .cbz is durable beside the original. Swap the row
    #    (path/size/page-count) and record the event in the caller's transaction,
    #    then remove the original CBR last.
    await session.execute(
        update(IssueFileRow)
        .where(IssueFileRow.id == issue_file_id)
        .values(path=str(dest), size=built.size, page_count=built.page_count)
    )
    history.record_event(
        session,
        event_type=history.EVENT_CONVERTED,
        series_id=series_id,
        issue_id=issue_id,
        download_id=download_id,
        source_title=source_title,
        source=source,
        data={
            "old_path": source_path,
            "new_path": str(dest),
            "size": built.size,
            "page_count": built.page_count,
        },
        now=now,
    )
    # Remove the original CBR last (after the row+event are staged). A failure
    # here is a leftover file, not data loss — logged, never fatal.
    try:
        await _run_fs(os.remove, source_path)
    except OSError as exc:  # pragma: no cover - leftover original is non-fatal
        logger.warning("convert: original %s not removed after swap: %s", source_path, exc)
    return str(dest)


def _record_failed(
    session: AsyncSession,
    *,
    series_id: int | None,
    issue_id: int | None,
    source: str | None,
    download_id: str | None,
    source_title: str | None,
    now,
    path: str,
    error: str,
) -> None:
    history.record_event(
        session,
        event_type=history.EVENT_CONVERT_FAILED,
        series_id=series_id,
        issue_id=issue_id,
        download_id=download_id,
        source_title=source_title,
        source=source,
        data={"path": path, "error": error},
        now=now,
    )


def _same_physical_file(a: str | os.PathLike[str], b: str | os.PathLike[str]) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.realpath(os.fspath(a)) == os.path.realpath(os.fspath(b))


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:  # pragma: no cover - best-effort cleanup
        logger.warning("convert: could not remove temp %s: %s", path, exc)


def _fsync_dir_quiet(directory: Path) -> None:
    try:
        fd = os.open(str(directory), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:  # pragma: no cover - platform cannot fsync a dir handle
        pass


__all__ = [
    "BuiltCbz",
    "ConvertError",
    "apply_conversion",
    "build_verified_cbz",
    "cbz_path_for",
    "is_cbr_file",
    "promote_cbz",
]
