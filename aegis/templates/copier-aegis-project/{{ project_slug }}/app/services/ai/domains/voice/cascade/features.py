"""Whisper's log-mel features in numpy, as Smart Turn hears them
(``turns``): what ``transformers``' ``WhisperFeatureExtractor`` makes for
8 seconds at 16 kHz (80 mels, a 25 ms window every 10 ms), without
``transformers``. Checked against it to the fifth decimal."""

from functools import cache
from typing import Any

RATE = 16_000
SECONDS = 8
N_FFT = 400
HOP = 160
MELS = 80


def _mel(hz: Any) -> Any:
    """Slaney's mel scale: linear below 1 kHz, logarithmic above."""
    import numpy as np

    hz = np.asarray(hz, dtype=np.float64)
    log = 15.0 + 27.0 * np.log(np.maximum(hz, 1e-10) / 1000.0) / np.log(6.4)
    return np.where(hz < 1000.0, 3.0 * hz / 200.0, log)


def _hz(mel: Any) -> Any:
    import numpy as np

    mel = np.asarray(mel, dtype=np.float64)
    return np.where(
        mel < 15.0,
        200.0 * mel / 3.0,
        1000.0 * np.exp(np.log(6.4) * (mel - 15.0) / 27.0),
    )


@cache
def _filters() -> Any:
    """The (frequency bins, mels) triangles, area-normalised (Slaney)."""
    import numpy as np

    bins = np.linspace(0, RATE // 2, N_FFT // 2 + 1)
    edges = _hz(np.linspace(_mel(0.0), _mel(RATE / 2), MELS + 2))
    widths = np.diff(edges)
    slopes = edges[None, :] - bins[:, None]
    down = -slopes[:, :-2] / widths[:-1]
    up = slopes[:, 2:] / widths[1:]
    triangles = np.maximum(0, np.minimum(down, up))
    return triangles * (2.0 / (edges[2:] - edges[:-2]))


def log_mel(audio: Any) -> Any:
    """``audio`` (float samples at 16 kHz) as Smart Turn's input: its last
    8 seconds, normalised to zero mean and unit variance, zero-padded to 8
    seconds after, as an (80, 800) float32 log-mel spectrogram."""
    import numpy as np

    size = RATE * SECONDS
    x = np.asarray(audio, dtype=np.float64)[-size:]
    x = (x - x.mean()) / np.sqrt(x.var() + 1e-7) if len(x) else x
    x = np.pad(x, (0, size - len(x)))
    padded = np.pad(x, N_FFT // 2, mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(padded, N_FFT)[::HOP]
    window = np.hanning(N_FFT + 1)[:-1]
    power = np.abs(np.fft.rfft(frames * window, axis=1)) ** 2
    spec = np.log10(np.maximum(power @ _filters(), 1e-10)).T[:, :-1]
    spec = np.maximum(spec, spec.max() - 8.0)
    return ((spec + 4.0) / 4.0).astype(np.float32)
