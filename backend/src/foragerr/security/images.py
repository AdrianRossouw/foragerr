"""OPDS page/cover image decode → downscale → encode, under strict caps
(FRG-OPDS-008, FRG-OPDS-012).

This is the codebase's only image-processing surface and it handles UNTRUSTED
bytes (image members pulled from library archives reachable via the OPDS
listener). It is deliberately narrow: one function, :func:`render_page`, that
lazily opens an image, rejects a decompression bomb on its declared dimensions
*before* decoding, downscales to a bounded width without ever upscaling, and
re-encodes to a web-friendly format. Every failure — over-cap, corrupt,
undecodable, or an unsupported mode — surfaces as a bounded
:class:`ImageRenderError`, never a crash or an unbounded allocation.

The per-request WALL-CLOCK timeout is NOT enforced here: :func:`render_page` is
synchronous and CPU-bounded by the caps only; the OPDS layer (area B) wraps this
call in ``asyncio.wait_for`` on an offload thread so a wedged decode never blocks
the event loop (design §4).

Two Pillow safety switches are set at import:

* ``Image.MAX_IMAGE_PIXELS`` is pinned to a safe global ceiling — Pillow's own
  decompression-bomb backstop that raises ``DecompressionBombError`` on a
  pathological image even if a caller passes a lax ``max_pixels``.
* ``LOAD_TRUNCATED_IMAGES`` is left DISABLED — on this untrusted path a truncated
  stream must fail loudly, not be silently completed with garbage padding.
"""

from __future__ import annotations

import io
import logging

from PIL import Image, ImageFile

logger = logging.getLogger(__name__)

#: Global Pillow decompression-bomb backstop (~64 megapixels). Independent of
#: the per-request ``max_pixels`` cap: this guards against a lax caller and is
#: enforced by Pillow itself during open/decode.
Image.MAX_IMAGE_PIXELS = 64_000_000

#: Untrusted-path defense-in-depth: a truncated/hostile stream must fail loudly,
#: not be silently completed with padding. ``LOAD_TRUNCATED_IMAGES`` defaults to
#: ``False``; we pin it so no import elsewhere can flip it for this path.
ImageFile.LOAD_TRUNCATED_IMAGES = False

#: Modes that carry real transparency and must round-trip as PNG.
_ALPHA_MODES = frozenset({"RGBA", "LA", "PA", "La"})


class ImageRenderError(Exception):
    """An image could not be rendered safely (FRG-OPDS-012).

    Raised by :func:`render_page` on a declared-dimension cap violation (checked
    BEFORE decode — the decompression-bomb guard), on undecodable/corrupt/
    truncated input, or on an unsupported/failed encode. The caller degrades to a
    bounded 4xx/5xx, never an unbounded allocation or a crash.
    """


def render_page(
    data: bytes, *, max_width: int | None, max_pixels: int
) -> tuple[bytes, str]:
    """Decode, downscale and re-encode one page image (FRG-OPDS-008/012).

    Steps, in order:

    1. **Lazy open** — ``Image.open`` reads only the header, so dimensions are
       known without decoding pixels.
    2. **Pixel cap BEFORE decode** — reject when ``width * height > max_pixels``
       *before* ``load()``. This is the decompression-bomb guard: a 100k×100k
       header is refused without ever allocating its pixels.
    3. **Decode** — ``load()`` fully reads the image (a truncated stream raises,
       because ``LOAD_TRUNCATED_IMAGES`` is off).
    4. **Downscale** — ``thumbnail`` to ``max_width`` with Lanczos, preserving
       aspect ratio and NEVER upscaling (a source narrower than ``max_width`` is
       returned at its own size).
    5. **Encode** — JPEG for opaque/photographic pages; PNG only when the source
       carries alpha.

    Returns ``(encoded_bytes, content_type)`` e.g. ``(b"...", "image/jpeg")``.
    Raises :class:`ImageRenderError` on any over-cap, corrupt or undecodable
    input. Synchronous and CPU-bounded by the caps (the wall-clock bound is the
    caller's concern).
    """
    try:
        img = Image.open(io.BytesIO(data))
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        # UnidentifiedImageError ⊂ OSError: garbage/non-image bytes land here.
        raise ImageRenderError(f"cannot open image: {exc}") from exc

    try:
        width, height = img.size
        if width <= 0 or height <= 0:
            raise ImageRenderError(
                f"image reports non-positive dimensions {width}x{height}"
            )
        if width * height > max_pixels:
            # Pre-``load()`` decompression-bomb rejection: no pixels allocated.
            raise ImageRenderError(
                f"image {width}x{height} ({width * height} px) exceeds the pixel "
                f"cap of {max_pixels}"
            )

        img.load()  # decode now; a truncated stream raises here (no LOAD_TRUNCATED)

        has_alpha = img.mode in _ALPHA_MODES or "transparency" in img.info

        if max_width is not None and img.width > max_width:
            # thumbnail() fits within the box preserving aspect and never
            # upscales; a huge height bound makes width the only constraint.
            img.thumbnail((max_width, 2**31 - 1), Image.LANCZOS)

        buffer = io.BytesIO()
        if has_alpha:
            out = img if img.mode == "RGBA" else img.convert("RGBA")
            out.save(buffer, format="PNG", optimize=True)
            content_type = "image/png"
        else:
            out = img if img.mode == "RGB" else img.convert("RGB")
            out.save(buffer, format="JPEG", quality=85)
            content_type = "image/jpeg"
        return buffer.getvalue(), content_type
    except ImageRenderError:
        raise
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        # Corrupt/truncated decode, an unsupported mode, or an encode failure.
        raise ImageRenderError(f"could not render image: {exc}") from exc
    finally:
        img.close()


__all__ = ["ImageRenderError", "render_page"]
