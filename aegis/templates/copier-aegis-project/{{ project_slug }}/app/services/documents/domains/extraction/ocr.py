"""Tier two of a read: Tesseract on the page render, before any model.

A page arrives three ways. A PDF somebody saved carries its own text
layer, read for free. A scan carries none, and until now went straight
to the vision model: a network call, a minute a page on a seven-page
letter, a few cents each. Most scans are typed, black on white - an
agency's letter, a statement - and Tesseract reads those locally in a
second. So OCR sits between the two: the model sees only the page OCR
could not make sense of, which is the handwritten or skewed one.

Tesseract is a system package (``tesseract-ocr`` plus a language) and
``pytesseract`` its wrapper; a machine without it reads as it did
before, with the model, rather than failing the page.
"""

from __future__ import annotations

import io
import re

# A page OCR did read: at least this share of its tokens look like
# words or figures. Below it the page is noise - a diagram, a photo, a
# page scanned upside down - and the model gets it.
MIN_WORD_SHARE = 0.6
_WORDLIKE = re.compile(r"[A-Za-z0-9$.,:;/()'\"%#&-]+")


def read_png(image: bytes) -> str | None:
    """Text off one page image, or None when Tesseract is not installed."""
    try:
        from PIL import Image
        import pytesseract
    except ImportError:
        return None
    try:
        with Image.open(io.BytesIO(image)) as page:
            return str(pytesseract.image_to_string(page))
    except Exception:  # noqa: BLE001 - no Tesseract, or bytes PIL cannot open
        # Either way the page is not lost: it goes to the model, as it
        # did before OCR existed.
        return None


def looks_like_text(text: str, minimum: int) -> bool:
    """Whether an OCR result is a reading or a guess."""
    words = text.split()
    if len(text.strip()) < minimum or not words:
        return False
    wordlike = sum(
        1 for w in words if _WORDLIKE.fullmatch(w) and any(c.isalnum() for c in w)
    )
    return wordlike / len(words) >= MIN_WORD_SHARE
