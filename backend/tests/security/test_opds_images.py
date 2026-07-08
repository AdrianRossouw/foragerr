"""OPDS page render (decode → downscale → encode) under strict caps
(FRG-OPDS-008, FRG-OPDS-012).

Fixtures are REAL images generated with Pillow so the decode path is exercised
end to end. The security cases prove the decompression-bomb guard fires on the
declared dimensions BEFORE any pixels are decoded, and that a truncated/garbage
stream fails loudly (``LOAD_TRUNCATED_IMAGES`` stays off on this untrusted path).
"""

from __future__ import annotations

import io
import os

import pytest
from PIL import Image, ImageFile

from foragerr.security.images import ImageRenderError, render_page

_BIG_PIXELS = 100_000_000  # a cap wide enough that small fixtures never trip it


def _jpeg(width: int, height: int, color=(200, 60, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, "JPEG")
    return buf.getvalue()


def _jpeg_noise(width: int, height: int) -> bytes:
    """A NOISE JPEG (poorly compressible), so a mid-stream truncation leaves the
    header intact but the scan data incomplete — the case that decodes only when
    ``LOAD_TRUNCATED_IMAGES`` is enabled and raises otherwise."""
    buf = io.BytesIO()
    Image.frombytes("RGB", (width, height), os.urandom(width * height * 3)).save(
        buf, "JPEG", quality=95
    )
    return buf.getvalue()


def _png_rgba(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (width, height), (10, 20, 30, 128)).save(buf, "PNG")
    return buf.getvalue()


# --- downscale / no-upscale (FRG-OPDS-008) -----------------------------------


@pytest.mark.req("FRG-OPDS-008")
def test_render_downscales_wide_source_to_max_width_preserving_aspect():
    data = _jpeg(400, 200)  # 2:1
    out, content_type = render_page(data, max_width=100, max_pixels=_BIG_PIXELS)
    assert content_type == "image/jpeg"
    img = Image.open(io.BytesIO(out))
    assert img.width <= 100
    assert img.width == 100  # width is the binding constraint
    # aspect ratio preserved (2:1 → height ~= width/2), allow a rounding pixel
    assert abs(img.height - img.width // 2) <= 1


@pytest.mark.req("FRG-OPDS-008")
def test_render_never_upscales_a_narrow_source():
    data = _jpeg(120, 80)
    out, _ = render_page(data, max_width=1000, max_pixels=_BIG_PIXELS)
    img = Image.open(io.BytesIO(out))
    assert (img.width, img.height) == (120, 80)  # unchanged, no upscale


@pytest.mark.req("FRG-OPDS-008")
def test_render_with_no_max_width_returns_source_dimensions():
    data = _jpeg(300, 150)
    out, _ = render_page(data, max_width=None, max_pixels=_BIG_PIXELS)
    img = Image.open(io.BytesIO(out))
    assert (img.width, img.height) == (300, 150)


@pytest.mark.req("FRG-OPDS-008")
def test_render_keeps_png_for_alpha_source():
    data = _png_rgba(60, 40)
    out, content_type = render_page(data, max_width=None, max_pixels=_BIG_PIXELS)
    assert content_type == "image/png"
    assert Image.open(io.BytesIO(out)).mode == "RGBA"


# --- resource caps / hostile input (FRG-OPDS-012) ----------------------------


@pytest.mark.req("FRG-OPDS-012")
def test_pixel_cap_rejects_before_decode():
    # A perfectly valid, decodable image whose dimensions exceed a low pixel cap:
    # the only way this raises is the pre-``load()`` dimension check — if control
    # reached decode/encode the render would succeed. So a raise here proves the
    # decompression-bomb guard fires on the header, before any pixels allocate.
    data = _jpeg(50, 50)  # 2500 px, a normal image
    with pytest.raises(ImageRenderError):
        render_page(data, max_width=None, max_pixels=100)  # 2500 > 100


@pytest.mark.req("FRG-OPDS-012")
def test_pixel_cap_boundary_allows_exactly_at_cap():
    data = _jpeg(50, 50)  # exactly 2500 px
    out, _ = render_page(data, max_width=None, max_pixels=2500)
    assert Image.open(io.BytesIO(out)).size == (50, 50)


@pytest.mark.req("FRG-OPDS-012")
def test_garbage_bytes_raise_render_error():
    with pytest.raises(ImageRenderError):
        render_page(b"this is definitely not an image", max_width=None,
                    max_pixels=_BIG_PIXELS)


@pytest.mark.req("FRG-OPDS-012")
def test_empty_bytes_raise_render_error():
    with pytest.raises(ImageRenderError):
        render_page(b"", max_width=None, max_pixels=_BIG_PIXELS)


@pytest.mark.req("FRG-OPDS-012")
def test_truncated_image_raises_render_error():
    # A valid JPEG cut off mid-stream: the header opens but the pixel decode
    # fails because LOAD_TRUNCATED_IMAGES is not enabled on this untrusted path.
    full = _jpeg(300, 300)
    truncated = full[: len(full) // 2]
    with pytest.raises(ImageRenderError):
        render_page(truncated, max_width=None, max_pixels=_BIG_PIXELS)


@pytest.mark.req("FRG-OPDS-012")
def test_render_resets_load_truncated_flag_per_call(monkeypatch):
    """FIX-7: ``LOAD_TRUNCATED_IMAGES`` is a process-global mutable flag; another
    module flipping it to True must NOT let a truncated stream decode on this
    untrusted path. ``render_page`` re-asserts ``False`` per call, so a mid-stream
    truncation still raises even with the global pre-set True — and the flag is
    left False afterwards."""
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)
    full = _jpeg_noise(400, 400)
    truncated = full[: int(len(full) * 0.6)]  # header intact, scan incomplete

    with pytest.raises(ImageRenderError):
        render_page(truncated, max_width=None, max_pixels=_BIG_PIXELS)
    # The per-call reset ran regardless of the global the caller set.
    assert ImageFile.LOAD_TRUNCATED_IMAGES is False


@pytest.mark.req("FRG-OPDS-011")
def test_force_jpeg_flattens_alpha_source_to_jpeg():
    """FIX-5a: the cover path forces JPEG so its ``.jpg`` cache + ``image/jpeg``
    content type stay truthful — an alpha source is flattened, never returned as
    mislabeled PNG bytes."""
    data = _png_rgba(60, 40)
    out, content_type = render_page(
        data, max_width=None, max_pixels=_BIG_PIXELS, force_jpeg=True
    )
    assert content_type == "image/jpeg"
    img = Image.open(io.BytesIO(out))
    assert img.format == "JPEG"
    assert img.mode == "RGB"  # flattened — no alpha channel survives
