"""How a voice says things, built from premade choices: a style to start
from, then its pace, energy, emotion and accent, and anything extra, put
together as the delivery instructions a speech model takes (OpenAI's
voices read the "Voice Affect / Tone / Pacing" form as instructions;
Gemini takes the same words as the line's ``speech_metadata`` style).

A voice profile keeps the choices (``tts_delivery``), so the voice designer
opens on them again, and the text they make (``tts_instructions``), which
is what is sent.
"""

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

# Each dial's choices: its value, and what it tells the model.
PACES = {
    "slow": "Slow and unhurried, with natural pauses",
    "natural": "Natural and conversational",
    "brisk": "Brisk and efficient, no filler",
}
ENERGIES = {
    "low": "Low-key and relaxed",
    "medium": "Engaged and even",
    "high": "Lively and animated",
}
EMOTIONS = {
    "neutral": "Neutral and composed",
    "warm": "Warm and caring",
    "upbeat": "Upbeat and positive",
    "serious": "Serious and measured",
}
ACCENTS = {
    "none": None,
    "american": "General American",
    "british": "Standard British",
    "australian": "Australian",
}
DIALS = {"pace": PACES, "energy": ENERGIES, "emotion": EMOTIONS, "accent": ACCENTS}


class Style(BaseModel):
    """A premade starting point: how it sounds, and where it sets the dials."""

    model_config = ConfigDict(frozen=True)

    label: str
    affect: str
    tone: str
    pace: str
    energy: str
    emotion: str

    @property
    def dials(self) -> dict[str, str]:
        """Where it sets the dials."""
        return {"pace": self.pace, "energy": self.energy, "emotion": self.emotion}


STYLES = {
    "calm": Style(
        label="Calm and warm",
        affect="Calm, warm and reassuring",
        tone="Friendly and unhurried",
        pace="slow",
        energy="low",
        emotion="warm",
    ),
    "professional": Style(
        label="Brisk and professional",
        affect="Composed and capable",
        tone="Clear and direct",
        pace="brisk",
        energy="medium",
        emotion="neutral",
    ),
    "cheerful": Style(
        label="Cheerful",
        affect="Bright and welcoming",
        tone="Upbeat and encouraging",
        pace="natural",
        energy="high",
        emotion="upbeat",
    ),
    "storyteller": Style(
        label="Storyteller",
        affect="Rich and engaging",
        tone="Expressive, drawing the listener in",
        pace="natural",
        energy="medium",
        emotion="warm",
    ),
    "support": Style(
        label="Empathetic support",
        affect="Gentle and patient",
        tone="Understanding, never rushed",
        pace="slow",
        energy="low",
        emotion="warm",
    ),
    "newsreader": Style(
        label="Newsreader",
        affect="Authoritative and polished",
        tone="Neutral and precise",
        pace="natural",
        energy="medium",
        emotion="serious",
    ),
}


class Delivery(BaseModel):
    """The choices: a style (or none), each dial, and anything extra."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    style: str | None = None
    pace: str = "natural"
    energy: str = "medium"
    emotion: str = "neutral"
    accent: str = "none"
    extra: str | None = None

    @model_validator(mode="after")
    def _on_offer(self) -> Self:
        if self.style is not None and self.style not in STYLES:
            raise ValueError(f"No style called {self.style}")
        for dial, choices in DIALS.items():
            if getattr(self, dial) not in choices:
                raise ValueError(f"{dial.title()}: pick one of {', '.join(choices)}")
        return self


def styled(style: str) -> Delivery:
    """A style's choices, its dials where it sets them."""
    return Delivery(style=style, **STYLES[style].dials)


def tuned(delivery: Delivery) -> bool:
    """Whether Fine-tune holds anything the style does not set: a dial off
    the style's (or Plain's) setting, or anything extra."""
    start = styled(delivery.style) if delivery.style else Delivery()
    off = any(getattr(delivery, dial) != getattr(start, dial) for dial in DIALS)
    return off or bool((delivery.extra or "").strip())


def compose(delivery: Delivery, accent: bool = True) -> str:
    """The choices as delivery instructions: the style's affect and tone,
    each dial, the accent where one is picked (and the model steers it:
    ``accent``), then anything extra."""
    lines = []
    if (preset := STYLES.get(delivery.style or "")) is not None:
        lines += [f"Voice Affect: {preset.affect}.", f"Tone: {preset.tone}."]
    lines += [
        f"Pacing: {PACES[delivery.pace]}.",
        f"Energy: {ENERGIES[delivery.energy]}.",
        f"Emotion: {EMOTIONS[delivery.emotion]}.",
    ]
    if accent and (spoken := ACCENTS[delivery.accent]):
        lines.append(f"Accent: {spoken}.")
    said = "\n".join(lines)
    extra = (delivery.extra or "").strip()
    return f"{said}\n\n{extra}" if extra else said
