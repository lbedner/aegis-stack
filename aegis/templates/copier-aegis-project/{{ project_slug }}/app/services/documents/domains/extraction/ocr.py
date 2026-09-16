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

# A page OCR did read: Tesseract's own mean word confidence is at least
# this. The token-shape test that came first passed a landscape table
# read sideways - every "word" was letters, none of them words - while
# Tesseract itself scored that page in the 30s. Its confidence is the
# signal; below it the page goes to the model.
MIN_CONFIDENCE = 70.0


def read_png(image: bytes) -> tuple[str, float] | None:
    """Text off one page image with Tesseract's mean word confidence
    (0-100), or None when Tesseract is not installed."""
    try:
        from PIL import Image
        import pytesseract
    except ImportError:
        return None
    try:
        with Image.open(io.BytesIO(image)) as page:
            data = pytesseract.image_to_data(page, output_type=pytesseract.Output.DICT)
    except Exception:  # noqa: BLE001 - no Tesseract, or bytes PIL cannot open
        # Either way the page is not lost: it goes to the model, as it
        # did before OCR existed.
        return None
    return _assemble(data)


def _assemble(data: dict[str, list]) -> tuple[str, float]:
    """Lines back out of Tesseract's word table, and the mean confidence
    of the words it was sure enough to score."""
    lines: dict[tuple[int, int, int], list[str]] = {}
    scores: list[float] = []
    for i, word in enumerate(data["text"]):
        if not str(word).strip():
            continue
        conf = float(data["conf"][i])
        if conf >= 0:
            scores.append(conf)
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(str(word))
    text = "\n".join(" ".join(words) for words in lines.values())
    return text, (sum(scores) / len(scores) if scores else 0.0)


def looks_like_text(text: str, confidence: float, minimum: int) -> bool:
    """Whether an OCR result is a reading or a guess."""
    return len(text.strip()) >= minimum and confidence >= MIN_CONFIDENCE
