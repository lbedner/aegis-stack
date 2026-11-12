"""Parakeet hearing in the app's own process (``onnx-asr``): no server and
no key. onnx-asr fetches the int8 model (about 670MB) from Hugging Face on
first use; PyAV decodes what the browser records (webm), which onnx-asr
cannot read."""

import asyncio
import io
import logging
from typing import Any

from .. import local
from ..models import (
    DEFAULT_STT_MODELS,
    AudioInput,
    STTProvider,
    TranscriptionResult,
)
from .providers import BaseSTTProvider

logger = logging.getLogger(__name__)

RATE = 16_000  # what Parakeet hears at


def decoded(content: bytes) -> Any:
    """Any audio file's sound as mono float samples at ``RATE``."""
    import av
    import numpy

    resampler = av.AudioResampler(format="flt", layout="mono", rate=RATE)
    with av.open(io.BytesIO(content)) as box:
        frames = [
            out for frame in box.decode(audio=0) for out in resampler.resample(frame)
        ]
    frames += resampler.resample(None)  # what it still holds
    return numpy.concatenate([f.to_ndarray().reshape(-1) for f in frames])


@local.loaded_once
def model(name: str) -> Any:
    """The one ``name`` this process hears with."""
    import onnx_asr

    return onnx_asr.load_model(name, quantization="int8")


class ParakeetProvider(BaseSTTProvider):
    """NVIDIA Parakeet TDT v3 in-process: 25 European languages, found from
    the audio (no language to set)."""

    provider_type = STTProvider.PARAKEET

    def __init__(self, model: str = DEFAULT_STT_MODELS[STTProvider.PARAKEET]) -> None:
        self.model = model

    def _heard(self, content: bytes) -> tuple[str, float]:
        samples = decoded(content)
        heard = model(self.model).recognize(samples, sample_rate=RATE)
        return heard, len(samples) / RATE

    async def transcribe(self, audio: AudioInput) -> TranscriptionResult:
        try:
            text, seconds = await asyncio.to_thread(self._heard, audio.content)
        except Exception as e:
            logger.error(f"Parakeet transcription failed: {e}")
            raise RuntimeError(f"Transcription failed: {e}") from e
        return TranscriptionResult(
            text=text.strip(),
            language=audio.language,
            duration_seconds=seconds,
            provider=self.provider_type,
        )
