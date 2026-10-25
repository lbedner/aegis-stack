"""What a voice is like, as the voice designer narrows by it: the tone
families a provider's tone words fall in, the tone a library voice's
description says, and the language an accent is spoken in.
"""

import re

# The handful of tone families the designer narrows by, each the words
# providers use for it (OpenAI's and Gemini's tones, and the words Gemini's
# library descriptions say most).
TONE_FAMILIES: dict[str, tuple[str, frozenset[str]]] = {
    "warm": (
        "Warm and soft",
        frozenset(
            {"Warm", "Soft", "Gentle", "Breathy", "Smooth", "Easy-going", "Friendly",
             "Casual", "Breezy", "Relaxed", "Laid-back", "Approachable", "Engaging",
             "Comforting", "Intimate", "Light"}
        ),
    ),
    "bright": (
        "Bright and upbeat",
        frozenset(
            {"Bright", "Upbeat", "Lively", "Excitable", "Youthful", "Forward",
             "Enthusiastic", "Energetic", "Fast-paced", "Cheerful"}
        ),
    ),
    "calm": (
        "Calm and even",
        frozenset(
            {"Calm", "Even", "Clear", "Mature", "Objective", "Cool", "Crisp",
             "Measured", "Soothing"}
        ),
    ),
    "firm": (
        "Firm and authoritative",
        frozenset(
            {"Firm", "Informative", "Knowledgeable", "Gravelly", "Professional",
             "Deep", "Resonant", "Textured", "Commanding", "Confident", "Direct"}
        ),
    ),
    "expressive": ("Expressive", frozenset({"Expressive", "Dramatic", "Animated"})),
}  # fmt: skip


def family_of(tone: str) -> str | None:
    """The family a provider's tone word falls in."""
    return next(
        (key for key, (_, tones) in TONE_FAMILIES.items() if tone in tones), None
    )


def tone_in(text: str) -> str | None:
    """The first tone word ``text`` says (a library voice's description:
    "Soft, calm, and soothing..."), as the families spell it."""
    known = {
        tone.lower(): tone for _, tones in TONE_FAMILIES.values() for tone in tones
    }
    return next(
        (known[w] for w in re.findall(r"[a-z-]+", text.lower()) if w in known), None
    )


# The accents spoken as English that do not say so: US regions, and the
# two OpenAI's voices have. Any other accent ends in its language
# ("Glasgow English", "Modern Standard Arabic") or is one ("German").
# ponytail: a word rule, a table per accent if a language ever breaks it
ENGLISH = frozenset(
    {"General American", "British", "East Coast", "West Coast", "Midwest",
     "Northwest", "Gulf Coast", "Inland Southern"}
)  # fmt: skip


def language_of(accent: str) -> str:
    """The language an accent is spoken in, as accents are grouped."""
    return "English" if accent in ENGLISH else accent.rsplit(" ", 1)[-1]
