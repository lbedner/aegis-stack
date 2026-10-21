"""The call's audio (``meetings.domains.bot.audio``): what the browser hears reaches
the bot a second at a time, and each second goes to whoever Meet's
captions say was talking then. Meet mixes the call into a few streams
that follow the loudest speakers, so a stream never says who it is."""

import asyncio
import base64
from pathlib import Path
import wave

from app.services.meetings.domains.bot.audio import (
    CHUNK_BYTES,
    Hearing,
    listen,
    speaker_at,
)
from tests._browser import live_browser
from tests._meetings import SECOND


def test_a_second_goes_to_whoever_was_captioned_then() -> None:
    """Captions show up a moment after the words (``CAPTION_LAG``)."""
    spoke = [(10.0, "Leonard"), (14.0, "Ada")]

    assert speaker_at(spoke, 9.0) == "Leonard"
    assert speaker_at(spoke, 12.6) == "Ada"
    assert speaker_at(spoke, 30.0) is None
    assert speaker_at([], 9.0) is None


def test_each_second_waits_for_its_captions_then_is_kept(tmp_path: Path) -> None:
    now = [10.0]
    hearing = Hearing(keep_in=tmp_path / "7", clock=lambda: now[0])
    hearing.heard(SECOND)
    now[0] = 13.0
    hearing.heard(SECOND)
    spoke = [(11.0, "Leonard"), (14.5, "Ada")]

    hearing.settle(spoke, now=13.0)
    assert hearing.seconds == {}
    hearing.settle(spoke, now=30.0)
    hearing.close()

    assert hearing.seconds == {"Leonard": 1.0, "Ada": 1.0}
    with wave.open(str(tmp_path / "7" / "Ada.wav")) as kept:
        assert (kept.getframerate(), kept.getnframes()) == (16_000, 16_000)


def test_nothing_is_kept_unless_asked(tmp_path: Path) -> None:
    hearing = Hearing(keep_in=None, clock=lambda: 10.0)
    hearing.heard(SECOND)

    hearing.settle([(10.0, "Ada")], now=30.0)
    hearing.close()

    assert hearing.seconds == {"Ada": 1.0}
    assert not any(tmp_path.iterdir())


# Two connections in one page, the first sending a tone (or silence) the
# second receives, the way Meet's page receives the call.
CALL = """async (gain) => {
  const ctx = new AudioContext();
  const tone = ctx.createOscillator(), level = ctx.createGain();
  level.gain.value = gain;
  const out = ctx.createMediaStreamDestination();
  tone.connect(level).connect(out);
  tone.start();
  const a = new RTCPeerConnection(), b = new RTCPeerConnection();
  a.onicecandidate = (e) => e.candidate && b.addIceCandidate(e.candidate);
  b.onicecandidate = (e) => e.candidate && a.addIceCandidate(e.candidate);
  b.ontrack = (e) => {
    const el = new Audio();
    el.srcObject = e.streams[0];
    el.muted = true;
    el.play();
  };
  out.stream.getTracks().forEach((t) => a.addTrack(t, out.stream));
  await a.setLocalDescription(await a.createOffer());
  await b.setRemoteDescription(a.localDescription);
  await b.setLocalDescription(await b.createAnswer());
  await a.setRemoteDescription(b.localDescription);
}"""


async def _heard(gain: float, seconds: float) -> list[bytes]:
    """What the bot is handed within ``seconds`` of a call playing a tone
    at ``gain``."""
    chunks: list[bytes] = []
    async with live_browser() as browser:
        page = await browser.new_page()
        await listen(page, lambda pcm: chunks.append(base64.b64decode(pcm)))
        await page.goto("about:blank")
        await page.evaluate(CALL, gain)
        for _ in range(int(seconds * 4)):
            if chunks:
                break
            await asyncio.sleep(0.25)
    return chunks


async def test_the_browser_hands_over_what_the_call_says() -> None:
    chunks = await _heard(0.5, seconds=10)

    assert chunks and len(chunks[0]) == CHUNK_BYTES


async def test_silence_is_not_sent() -> None:
    assert await _heard(0.0, seconds=3) == []
