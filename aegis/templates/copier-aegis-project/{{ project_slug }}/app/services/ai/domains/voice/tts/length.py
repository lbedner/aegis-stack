"""How long a line of speech is, read from its audio: what a model billed
by the second of speech is priced by."""

import io
import wave

from ..models import AudioFormat

# Layer III bitrates (kbps) by header index: MPEG-1, then MPEG-2 and 2.5.
_KBPS = {
    True: (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    False: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
}
# Sample rates by the header's version bits (3 MPEG-1, 2 MPEG-2, 0 MPEG-2.5).
_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


def wav_seconds(wav: bytes) -> float | None:
    """A WAV's length, from its header."""
    try:
        with wave.open(io.BytesIO(wav)) as w:
            return w.getnframes() / w.getframerate()
    except (wave.Error, EOFError):
        return None


def _id3_size(mp3: bytes) -> int:
    """The leading ID3 tag's length (its size is synchsafe: 7 bits a byte)."""
    if mp3[:3] != b"ID3" or len(mp3) < 10:
        return 0
    size = 0
    for byte in mp3[6:10]:
        size = size << 7 | byte & 0x7F
    return 10 + size


def mp3_seconds(mp3: bytes) -> float | None:
    """An MP3's (Layer III) length, frame by frame, so a variable bitrate
    counts too; it ends at the first thing that is not a frame."""
    at, seconds = _id3_size(mp3), 0.0
    while at + 4 <= len(mp3):
        head = int.from_bytes(mp3[at : at + 4], "big")
        version, kbps_at, rate_at = head >> 19 & 3, head >> 12 & 15, head >> 10 & 3
        layer_3 = head >> 17 & 3 == 1
        if head >> 21 != 0x7FF or not layer_3 or version == 1:
            break
        if kbps_at in (0, 15) or rate_at == 3:
            break
        mpeg_1 = version == 3
        kbps, rate = _KBPS[mpeg_1][kbps_at], _RATES[version][rate_at]
        samples = 1152 if mpeg_1 else 576
        seconds += samples / rate
        at += samples // 8 * kbps * 1000 // rate + (head >> 9 & 1)
    return seconds or None


def seconds(audio: bytes, format: AudioFormat) -> float | None:
    """A line's length, for the formats speech comes back in; None when it
    cannot be read."""
    if format == AudioFormat.WAV:
        return wav_seconds(audio)
    if format == AudioFormat.MP3:
        return mp3_seconds(audio)
    return None
