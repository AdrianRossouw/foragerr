"""Comic-archive media types for OPDS download links (FRG-OPDS-005).

Mylar served every download as ``application/octet-stream``; foragerr serves
the RFC-registered comic types so OPDS readers (Chunky, Panels, KyBook) pick
the right viewer. The map is by file extension only — never sniffed from
archive contents, so resolving a media type opens no file.
"""

from __future__ import annotations

from pathlib import Path

#: Extension -> specific media type. M1's import pipeline only ever writes
#: ``.cbz``/``.cbr``; ``.pdf`` is included for completeness.
COMIC_MEDIA_TYPES: dict[str, str] = {
    ".cbz": "application/vnd.comicbook+zip",
    ".cbr": "application/vnd.comicbook-rar",
    ".pdf": "application/pdf",
}

#: Ultimate fallback for an extension outside the known comic set. Managed
#: content never reaches this (import writes only comic archives); kept
#: explicit rather than guessing a wrong specific type.
FALLBACK_MEDIA_TYPE = "application/octet-stream"


def media_type_for(path: str | Path) -> str:
    """The specific media type for ``path`` by its extension (case-folded)."""
    return COMIC_MEDIA_TYPES.get(Path(path).suffix.lower(), FALLBACK_MEDIA_TYPE)
