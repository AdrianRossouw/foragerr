"""Archive test helpers for the importer package (uniquely named, like
``tests/parser/corpus.py``, so importing it never shadows the root conftest)."""

from __future__ import annotations

import zipfile
from pathlib import Path

# A genuine 1x1 PNG so a cbz has a real image entry (FRG-PP-006).
_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f9f0000000049454e44ae42"
    "6082"
)


def make_cbz(path: Path, *, images: int = 1, junk: bool = False) -> int:
    """Write a valid cbz (zip with ``images`` image entries). Returns its size."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for i in range(images):
            zf.writestr(f"page{i:03d}.png", _PNG_1x1)
        if junk:
            zf.writestr("readme.txt", b"not an image")
    return path.stat().st_size


def make_corrupt(path: Path, *, name: str = "bad.cbz") -> Path:
    """Write a file with a comic extension whose bytes are not a valid zip."""
    target = path if path.suffix else path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"<html>404 not found</html>")
    return target


def comicinfo_xml(
    *,
    series: str | None = "Batman",
    number: str | None = "404",
    title: str | None = None,
    cv_issue_id: int | None = 9001,
    web: bool = True,
    notes: bool = False,
    pad_bytes: int = 0,
) -> str:
    """Build a ComicInfo.xml body. ``web``/``notes`` control which carrier holds
    the ComicVine id (``4000-<id>`` in <Web>, "[Issue ID <id>]" in <Notes>);
    ``pad_bytes`` inflates the declared size (oversized-member tests)."""
    lines = ['<?xml version="1.0"?>', "<ComicInfo>"]
    if series is not None:
        lines.append(f"  <Series>{series}</Series>")
    if number is not None:
        lines.append(f"  <Number>{number}</Number>")
    if title is not None:
        lines.append(f"  <Title>{title}</Title>")
    if web and cv_issue_id is not None:
        lines.append(
            f"  <Web>https://comicvine.gamespot.com/x/4000-{cv_issue_id}/</Web>"
        )
    if notes and cv_issue_id is not None:
        lines.append(f"  <Notes>Tagged anon [Issue ID {cv_issue_id}]</Notes>")
    if pad_bytes:
        lines.append(f"  <!--{'x' * pad_bytes}-->")
    lines.append("</ComicInfo>")
    return "\n".join(lines)


def make_cbz_with_comicinfo(
    path: Path,
    *,
    xml: str,
    images: int = 1,
    member_name: str = "ComicInfo.xml",
    filler_bytes: int = 0,
) -> int:
    """Write a valid cbz that additionally carries a ``member_name`` XML member.

    ``filler_bytes`` adds an incompressible image member so the archive can be
    pushed above the junk-size floor when a real-sized comic is needed."""
    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for i in range(images):
            zf.writestr(f"page{i:03d}.png", _PNG_1x1)
        if filler_bytes:
            zf.writestr("page_big.png", os.urandom(filler_bytes))
        zf.writestr(member_name, xml)
    return path.stat().st_size
