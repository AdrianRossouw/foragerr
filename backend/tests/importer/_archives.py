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
