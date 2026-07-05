"""Download-side content verification (FRG-DDL-010).

The gate every completed DDL file passes before it may enter the import
pipeline. This is the *download-side* check (mylar-ddl §4 — the CRC test does
not authenticate content, and the single hardcoded upstream means a takeover is
a malware channel): magic bytes must match a supported comic container, a
``.cbz`` must open as a real zip with at least one image entry (stdlib
``zipfile``, NO extraction — extraction is the import area's job), and the file
must clear a minimum plausible size floor. A failure counts as a download
failure so the queue engine fails over to the next host, then to the standard
failed pipeline when hosts are exhausted.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

from foragerr.ddl.errors import DdlDownloadError

#: Minimum plausible size for a real comic file (FRG-DDL-010 size floor). An
#: HTML click-bait/ad page or a truncated transfer falls well under this.
SIZE_FLOOR_BYTES = 10_240

#: Image entry extensions that make a zip a plausible CBZ (≥1 required).
_IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"})

#: Magic-number prefixes → (detected kind, final extension).
_ZIP_MAGIC = b"PK\x03\x04"
_ZIP_EMPTY_MAGIC = b"PK\x05\x06"  # empty archive
_RAR4_MAGIC = b"Rar!\x1a\x07\x00"
_RAR5_MAGIC = b"Rar!\x1a\x07\x01\x00"
_PDF_MAGIC = b"%PDF"


@dataclass(frozen=True, slots=True)
class VerifiedFile:
    """The verified type + the safe final extension to name the file with."""

    kind: str  # "zip" | "rar" | "pdf"
    ext: str  # ".cbz" | ".cbr" | ".pdf"


def _read_magic(path: Path, n: int = 8) -> bytes:
    with path.open("rb") as handle:
        return handle.read(n)


def verify_file(path: Path) -> VerifiedFile:
    """Verify a completed download or raise :class:`DdlDownloadError`.

    Order: size floor → magic-number type → (zip only) opens as a zip with ≥1
    image entry. Returns the detected kind + the safe extension the final name
    should carry (never a remote-supplied extension, FRG-DDL-011)."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise DdlDownloadError(f"verify: cannot stat file: {exc}") from exc
    if size < SIZE_FLOOR_BYTES:
        raise DdlDownloadError(
            f"verify: file {size}B is below the {SIZE_FLOOR_BYTES}B size floor "
            "(click-bait/ad page or truncated transfer)"
        )
    magic = _read_magic(path)
    if magic.startswith(_ZIP_MAGIC) or magic.startswith(_ZIP_EMPTY_MAGIC):
        _verify_zip_has_image(path)
        return VerifiedFile(kind="zip", ext=".cbz")
    if magic.startswith(_RAR4_MAGIC) or magic.startswith(_RAR5_MAGIC):
        return VerifiedFile(kind="rar", ext=".cbr")
    if magic.startswith(_PDF_MAGIC):
        return VerifiedFile(kind="pdf", ext=".pdf")
    raise DdlDownloadError(
        "verify: magic bytes match no supported comic container "
        "(zip/rar/pdf) — likely an HTML error page named as a comic"
    )


def _verify_zip_has_image(path: Path) -> None:
    """A CBZ must open as a valid zip with ≥1 image entry (no extraction)."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    except zipfile.BadZipFile as exc:
        raise DdlDownloadError(f"verify: not a valid zip archive: {exc}") from exc
    has_image = any(
        Path(name).suffix.lower() in _IMAGE_EXTS for name in names
    )
    if not has_image:
        raise DdlDownloadError(
            "verify: zip contains no image entries — not a comic archive"
        )


__all__ = ["SIZE_FLOOR_BYTES", "VerifiedFile", "verify_file"]
