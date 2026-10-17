"""The call's audio, from the browser to the bot, each second given to
whoever was talking.

The page is hooked before Meet loads (``listen``): every audio track the
call sends is read as 16 kHz mono PCM, a second at a time, and handed to
the bot over the Playwright connection it already drives, so no socket
of its own is opened and nothing outside the bot's process can send in.
A silent second is dropped in the page.

Meet mixes the call into a few streams that follow the loudest speakers,
so a stream never says who it is. Meet's captions do: a second goes to
the speaker whose caption changed nearest to when it was heard
(``speaker_at``), once the captions have had time to catch up.

The seconds heard per speaker are kept on the meeting; the audio only
when ``MEETINGS_KEEP_AUDIO_DIR`` names a folder: then each speaker's audio
is a WAV there, under the meeting's id.
"""

import asyncio
import base64
from bisect import bisect_left
from collections.abc import Callable
from pathlib import Path
import re
import wave

from playwright.async_api import Page

from app.services.meetings.models import UNKNOWN

RATE = 16_000
# One second of 16-bit mono: what the page sends at a time.
CHUNK_BYTES = RATE * 2
# Captions show up this long after the words; a caption change further
# than NEAR seconds from a second says nothing about who spoke in it.
CAPTION_LAG = 1.5
NEAR = 3.0

BINDING = "__meetingAudio"
# Hooks RTCPeerConnection before the page's own scripts run: each remote
# audio track is read with MediaStreamTrackProcessor, mixed to mono,
# resampled to 16 kHz and sent as base64 PCM16, a second at a time,
# unless it was silent (its loudest sample under 1%).
HEAR_CALL = """(() => {
  if (!window.MediaStreamTrackProcessor) return;
  const Native = window.RTCPeerConnection;
  const RATE = __RATE__, QUIET = 327;
  const heard = new WeakSet();
  const send = (pcm) => {
    if (!pcm.some((s) => s > QUIET || s < -QUIET)) return;
    const bytes = new Uint8Array(pcm.buffer);
    let text = '';
    for (let i = 0; i < bytes.length; i += 0x8000) {
      text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    }
    window.__BINDING__(btoa(text));
  };
  async function hear(track) {
    if (track.kind !== 'audio' || heard.has(track)) return;
    heard.add(track);
    const reader = new MediaStreamTrackProcessor({track}).readable.getReader();
    // One second's buffer, reused: send has copied it out before it refills.
    const out = new Int16Array(RATE);
    let n = 0, at = 0, mono = new Float32Array(0), plane = mono;
    for (;;) {
      const {value: frame, done} = await reader.read();
      if (done) return;
      const length = frame.numberOfFrames, channels = frame.numberOfChannels;
      if (mono.length !== length) {
        mono = new Float32Array(length);
        plane = new Float32Array(length);
      }
      mono.fill(0);
      for (let c = 0; c < channels; c++) {
        frame.copyTo(plane, {planeIndex: c, format: 'f32-planar'});
        for (let i = 0; i < length; i++) mono[i] += plane[i] / channels;
      }
      const step = frame.sampleRate / RATE;
      frame.close();
      for (; at < length; at += step) {
        out[n++] = Math.max(-1, Math.min(1, mono[at | 0])) * 32767;
        if (n === RATE) {
          send(out);
          n = 0;
        }
      }
      at -= length;
    }
  }
  window.RTCPeerConnection = class extends Native {
    constructor(...args) {
      super(...args);
      this.addEventListener('track', (event) => hear(event.track));
    }
  };
})()""".replace("__RATE__", str(RATE)).replace("__BINDING__", BINDING)


async def listen(page: Page, on_audio: Callable[[str], None]) -> None:
    """Hand ``on_audio`` every second of the call ``page`` is about to open,
    as base64 PCM16; before its first navigation."""
    await page.expose_function(BINDING, on_audio)
    await page.add_init_script(HEAR_CALL)


def speaker_at(spoke: list[tuple[float, str]], at: float) -> str | None:
    """Who was talking at ``at``: the speaker whose caption changed nearest
    to when the words would be captioned, or None when none changed near.
    ``spoke`` is (time, speaker) in time order."""
    if not spoke:
        return None
    when = at + CAPTION_LAG
    i = bisect_left(spoke, when, key=lambda s: s[0])
    # ponytail: nearest single change; overlapping speakers both changing in
    # one look go to one of them, split by loudness per stream if that matters.
    near = min(spoke[max(i - 1, 0) : i + 1], key=lambda s: abs(s[0] - when))
    return near[1] if abs(near[0] - when) <= NEAR else None


class Hearing:
    """One run's audio: each second as it arrives (``heard``), given to its
    speaker once the captions have caught up (``settle``), counted, and
    kept when ``keep_in`` names a folder."""

    def __init__(
        self, keep_in: Path | None, clock: Callable[[], float] | None = None
    ) -> None:
        self.keep_in = keep_in
        self.clock = clock or (lambda: asyncio.get_running_loop().time())
        self.waiting: list[tuple[float, bytes]] = []
        self.seconds: dict[str, float] = {}
        self.kept: dict[str, wave.Wave_write] = {}

    def heard(self, pcm: str) -> None:
        self.waiting.append((self.clock(), base64.b64decode(pcm)))

    def settle(self, spoke: list[tuple[float, str]], now: float) -> None:
        """Give each second its captions have caught up with to its speaker."""
        ready = now - CAPTION_LAG - NEAR
        while self.waiting and self.waiting[0][0] <= ready:
            at, pcm = self.waiting.pop(0)
            speaker = speaker_at(spoke, at) or UNKNOWN
            seconds = self.seconds.get(speaker, 0.0)
            self.seconds[speaker] = seconds + len(pcm) / CHUNK_BYTES
            if self.keep_in is not None:
                self._file(speaker).writeframes(pcm)

    def _file(self, speaker: str) -> wave.Wave_write:
        if speaker not in self.kept:
            folder: Path = self.keep_in  # type: ignore[assignment]
            folder.mkdir(parents=True, exist_ok=True)
            name = re.sub(r"[^\w .-]", "_", speaker).strip() or UNKNOWN
            # Open for the whole call, closed by ``close``.
            kept = wave.open(str(folder / f"{name}.wav"), "wb")  # noqa: SIM115
            kept.setnchannels(1)
            kept.setsampwidth(2)
            kept.setframerate(RATE)
            self.kept[speaker] = kept
        return self.kept[speaker]

    def close(self) -> None:
        for kept in self.kept.values():
            kept.close()
