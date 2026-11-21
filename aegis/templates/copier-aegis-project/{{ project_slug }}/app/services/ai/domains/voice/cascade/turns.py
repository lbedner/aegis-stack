"""When the caller is done talking, for a cascade call (``connection``).

Silero VAD hears speech in each 32 ms window. At each pause, Smart Turn
v3.2 judges whether the turn is over or the caller only paused mid-thought
("I'd like to... um"): an unfinished turn waits for more speech, and a long
enough silence ends it whatever Smart Turn says. A turn is heard whole from
a moment before its first word, so the first syllable is not cut.

Both run on ``onnxruntime`` on the CPU (Silero is 2 MB, Smart Turn 8 MB,
about 10 ms a judgement), fetched on first use into the cache
(``local.fetched``). Smart Turn reads Whisper's features, made in numpy
(``features``): no torch, no ``transformers``.
"""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .. import local
from ..tts import realtime
from . import features

RATE = features.RATE
# Silero's window at 16 kHz, and the context it carries between windows.
WINDOW = 512
CONTEXT = 64
WINDOW_MS = WINDOW * 1000 // RATE
SPEECH = 0.5  # Silero's probability a window is speech
PAUSE_MS = 200  # quiet this long is a pause, which Smart Turn judges
DONE = 0.5  # Smart Turn's probability the turn is over
GIVE_UP_MS = 2000  # quiet this long ends the turn, finished or not
PREROLL_MS = 300  # kept from before the first word

CACHE = Path.home() / ".cache" / "turn-detection"
SILERO = (
    "https://raw.githubusercontent.com/snakers4/silero-vad/v6.2"
    "/src/silero_vad/data/silero_vad.onnx"
)
SMART_TURN = (
    "https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/main"
    "/smart-turn-v3.2-cpu.onnx"
)


@local.loaded_once
def _model(url: str) -> Any:
    """One ONNX session per model for the process, on one CPU thread each."""
    import onnxruntime

    options = onnxruntime.SessionOptions()
    options.inter_op_num_threads = 1
    options.intra_op_num_threads = 1
    path = str(local.fetched(url, CACHE))
    return onnxruntime.InferenceSession(
        path, sess_options=options, providers=["CPUExecutionProvider"]
    )


class Silero:
    """Speech, a window at a time: its state carries from one window to
    the next, so each call has its own."""

    def __init__(self) -> None:
        import numpy as np

        self._np = np
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, CONTEXT), dtype=np.float32)

    def __call__(self, window: Any) -> float:
        np = self._np
        x = np.concatenate((self._context, window[None, :]), axis=1)
        out, self._state = _model(SILERO).run(
            None, {"input": x, "state": self._state, "sr": np.array(RATE, np.int64)}
        )
        self._context = x[:, -CONTEXT:]
        return float(out[0][0])


def smart_turn(audio: Any) -> float:
    """The probability the caller is done, from the turn so far."""
    spec = features.log_mel(audio)[None, :, :]
    return float(_model(SMART_TURN).run(None, {"input_features": spec})[0][0][0])


@dataclass
class Heard:
    """``start``: the caller began talking (a reply playing is cut off).
    ``end``: they are done; ``audio`` is the turn, PCM16 at 16 kHz."""

    kind: Literal["start", "end"]
    audio: bytes = b""


class Listener:
    """One call's ear: PCM16 at 16 kHz in, in pieces of any size; what was
    heard out. ``vad`` and ``done`` stand in for Silero and Smart Turn."""

    def __init__(
        self,
        vad: Callable[[Any], float] | None = None,
        done: Callable[[Any], float] | None = None,
    ) -> None:
        import numpy as np

        self._np = np
        self._vad = vad or Silero()
        self._done = done or smart_turn
        self._rest = b""
        self._before: deque[Any] = deque(maxlen=-(-PREROLL_MS // WINDOW_MS))
        self._turn: list[Any] = []
        self._quiet = 0
        self._judged = False

    def hear(self, pcm: bytes) -> list[Heard]:
        """What ``pcm``, after what came before it, makes heard."""
        np = self._np
        data, size = self._rest + pcm, WINDOW * 2
        whole = len(data) - len(data) % size
        self._rest = data[whole:]
        heard: list[Heard] = []
        for i in range(0, whole, size):
            window = np.frombuffer(data[i : i + size], "<i2").astype(np.float32)
            heard += self._window(window / 32768.0)
        return heard

    def _window(self, window: Any) -> list[Heard]:
        speaking = self._vad(window) >= SPEECH
        if not self._turn:
            self._before.append(window)
            if not speaking:
                return []
            self._turn, self._quiet, self._judged = list(self._before), 0, False
            self._before.clear()
            return [Heard("start")]
        self._turn.append(window)
        if speaking:
            self._quiet, self._judged = 0, False
            return []
        self._quiet += WINDOW_MS
        if self._quiet >= PAUSE_MS and not self._judged:
            self._judged = True
            if self._done(self._np.concatenate(self._turn)) >= DONE:
                return [self._ended()]
        return [self._ended()] if self._quiet >= GIVE_UP_MS else []

    def _ended(self) -> Heard:
        audio = self._np.concatenate(self._turn)
        self._turn = []
        return Heard("end", realtime.pcm16(audio))
