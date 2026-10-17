"""Meetings settings, kept out of config.py's size budget.

``Settings`` inherits these, so they load from ``.env`` like every other
setting.
"""

from pydantic_settings import BaseSettings


class MeetingsSettings(BaseSettings):
    # The first agent's Google sign-in (Playwright's storage_state, as JSON),
    # kept by ``meetings login`` in the secrets store; one set here wins.
    # Another agent's is kept under ``<this>__<NAME>``. Its suffix keeps it
    # out of a ``Settings`` repr.
    MEETINGS_BOT_LOGIN_SECRET: str | None = None
    # A folder to keep each meeting's audio in, one WAV per speaker under the
    # meeting's id (``meetings.audio``); unset, the audio is heard, not kept.
    MEETINGS_KEEP_AUDIO_DIR: str | None = None
