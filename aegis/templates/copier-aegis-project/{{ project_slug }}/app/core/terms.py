"""Terms found in free text (an answer read aloud, a line of a call): each
a whole word in any case, the longest first, known by one spelling
whatever its case (``term_key``). A match whose case does not fold back to
its term (a dotted capital I) is no term: look it up with ``.get``."""

from collections.abc import Iterable
import re


def term_key(term: str) -> str:
    """The one spelling a term is known by, whatever its case."""
    return term.strip().lower()


def terms_pattern(terms: Iterable[str]) -> re.Pattern[str]:
    """Any of ``terms``, as a whole word in any case; the longest first, so
    "the change queue" is found before "the queue". With none, nothing."""
    longest = sorted(terms, key=len, reverse=True)
    words = "|".join(map(re.escape, longest)) or "(?!)"
    return re.compile(rf"(?<!\w)(?:{words})(?!\w)", re.IGNORECASE)
