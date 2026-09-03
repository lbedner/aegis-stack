"""The PDF engine behind extraction, and a PNG encoder for its pages.

pypdfium2 (Google's PDFium) does both jobs this needs: the text layer
where a PDF has one, and rendering a page to pixels where it does not.
The import is lazy so the service boots in an image built before the
dependency landed; only extraction itself needs it.

The PNG encoder is the standard library: pypdfium2 hands back a raw
RGBA bitmap and would otherwise need Pillow just to write it out.
"""

from __future__ import annotations

import struct
from typing import Any
import zlib

# Rendering scale over 72 dpi: 2.0 gives 144 dpi, enough for a vision
# model to read body text and for a thumbnail to be crisp.
RENDER_SCALE = 2.0

PNG_MEDIA_TYPE = "image/png"


class PdfPages:
    """One opened PDF: how many pages, the text layer of each, a render."""

    def __init__(self, data: bytes) -> None:
        import pypdfium2 as pdfium  # lazy: see module docstring

        self._doc = pdfium.PdfDocument(data)

    def __len__(self) -> int:
        return len(self._doc)

    def text(self, page_number: int) -> str:
        """The page's own text layer, blank for a scan."""
        page = self._doc[page_number - 1]
        try:
            return page.get_textpage().get_text_range().strip()
        finally:
            page.close()

    def render_png(self, page_number: int, *, scale: float = RENDER_SCALE) -> bytes:
        page = self._doc[page_number - 1]
        try:
            bitmap: Any = page.render(scale=scale, rev_byteorder=True, prefer_bgrx=True)
        finally:
            page.close()
        return encode_png(
            bitmap.width,
            bitmap.height,
            bytes(bitmap.buffer),
            bitmap.stride,
            bitmap.n_channels,
        )

    def close(self) -> None:
        self._doc.close()


def encode_png(
    width: int, height: int, pixels: bytes, stride: int, channels: int
) -> bytes:
    """A PNG from a packed RGB or RGBA buffer, no filtering, stdlib only."""
    if channels not in (3, 4):
        raise ValueError(
            f"encode_png takes RGB or RGBA pixels, not {channels} channels"
        )
    row_bytes = width * channels
    raw = bytearray()
    for y in range(height):
        start = y * stride
        raw += b"\x00" + pixels[start : start + row_bytes]

    def chunk(kind: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    color_type = 6 if channels == 4 else 2
    header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )
