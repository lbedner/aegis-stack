"""A cascade call's ear (``cascade.turns``): Silero hears speech window by
window, and at each pause Smart Turn judges whether the caller is done.
Both models are stood in for here; the features Smart Turn reads are
checked against ``transformers``' own (values captured from it)."""

import numpy as np
import pytest

from app.services.ai.domains.voice.cascade import features, turns
from app.services.ai.domains.voice.cascade.turns import Listener
from tests._cascade import (
    LOUD,
    QUIET,
    WINDOW_BYTES,
    pause,
    speech,
    windows,
    windows_for,
)


def test_a_finished_turn_is_heard_whole_from_just_before_it_began() -> None:
    """Its audio starts a moment before the first window heard as speech,
    so the first syllable is not cut."""
    judged: list[int] = []

    def done(audio: np.ndarray) -> float:
        judged.append(len(audio))
        return 0.9

    ear = Listener(vad=speech, done=done)
    before = windows(QUIET, QUIET)
    heard = ear.hear(before + windows(LOUD, LOUD) + pause())

    assert [h.kind for h in heard] == ["start", "end"]
    assert len(judged) == 1
    assert len(heard[1].audio) == len(before) + 2 * WINDOW_BYTES + len(pause())


def test_a_pause_mid_thought_waits_for_more() -> None:
    """Smart Turn says not done: the turn goes on through the pause, and is
    judged again at the next one."""
    verdicts = iter([0.1, 0.9])
    ear = Listener(vad=speech, done=lambda audio: next(verdicts))
    quiet = pause()

    first = ear.hear(windows(LOUD) + quiet)
    second = ear.hear(windows(LOUD) + quiet)

    assert [h.kind for h in first] == ["start"]
    assert [h.kind for h in second] == ["end"]
    assert len(second[0].audio) > 2 * len(quiet)


def test_a_long_enough_silence_ends_the_turn_whatever_smart_turn_says() -> None:
    ear = Listener(vad=speech, done=lambda audio: 0.0)

    heard = ear.hear(windows(LOUD) + windows(*[QUIET] * windows_for(turns.GIVE_UP_MS)))

    assert [h.kind for h in heard] == ["start", "end"]


def test_audio_in_pieces_of_any_size_is_heard_the_same() -> None:
    """The page sends frames that are not Silero's window: the rest waits
    for the next piece."""
    audio = windows(QUIET, LOUD, LOUD) + pause()
    ear = Listener(vad=speech, done=lambda audio: 0.9)

    heard = [h for i in range(0, len(audio), 333) for h in ear.hear(audio[i : i + 333])]

    assert [h.kind for h in heard] == ["start", "end"]
    assert ear.hear(b"") == []


def test_silence_alone_is_no_turn() -> None:
    ear = Listener(vad=speech, done=lambda audio: pytest.fail("judged nothing"))
    assert ear.hear(windows(*[QUIET] * 40)) == []


def test_the_features_are_whispers() -> None:
    """Two seconds of a 440 Hz tone, as ``WhisperFeatureExtractor(
    chunk_length=8)`` makes them (normalised, padded to 8 s)."""
    t = np.arange(16_000 * 2) / 16_000
    spec = features.log_mel((0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32))

    assert spec.shape == (80, 800) and spec.dtype == np.float32
    for (mel, frame), value in {
        (0, 0): 1.20905,
        (10, 50): 1.57451,
        (13, 100): -0.33602,
        (5, 700): -0.33602,
    }.items():
        assert spec[mel, frame] == pytest.approx(value, abs=1e-4)
    assert spec.mean() == pytest.approx(-0.30882, abs=1e-4)
