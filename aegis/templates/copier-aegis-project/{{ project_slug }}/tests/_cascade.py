"""Stand-ins for a cascade call's ear (``cascade.turns``): audio made of
whole Silero windows, and a VAD that hears any loud window as speech, so
neither model is downloaded."""

import numpy as np

from app.services.ai.domains.voice.cascade import turns

LOUD, QUIET = 1000, 0
WINDOW_BYTES = turns.WINDOW * 2  # PCM16


def windows(*levels: int) -> bytes:
    """One window of PCM16 per level, every sample at it."""
    return b"".join(
        np.full(turns.WINDOW, level, dtype="<i2").tobytes() for level in levels
    )


def windows_for(ms: int) -> int:
    """How many windows last ``ms``, rounded up."""
    return -(-ms // turns.WINDOW_MS)


def pause() -> bytes:
    """Quiet long enough to be a pause Smart Turn judges."""
    return windows(*[QUIET] * windows_for(turns.PAUSE_MS))


def speech(window: np.ndarray) -> float:
    """Silero stood in for: a loud window is speech."""
    return 0.9 if np.abs(window).max() > 0.01 else 0.0


def ear() -> turns.Listener:
    """A listener for whom every pause ends the turn."""
    return turns.Listener(vad=speech, done=lambda audio: 0.9)


def turn() -> bytes:
    """A spoken turn: speech, then a pause that ends it."""
    return windows(*[LOUD] * 4) + pause()
