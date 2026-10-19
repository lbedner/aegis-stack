"""Meetings settings, kept out of config.py's size budget.

``Settings`` inherits these, so they load from ``.env`` like every other
setting.
"""

from typing import Annotated

from pydantic_settings import BaseSettings

from app.core.configurable import Configurable

OWNER = "service_meetings"


class MeetingsSettings(BaseSettings):
    # The first agent's Google sign-in (Playwright's storage_state, as JSON),
    # kept by ``meetings login`` in the secrets store; one set here wins.
    # Another agent's is kept under ``<this>__<NAME>``. Its suffix keeps it
    # out of a ``Settings`` repr.
    MEETINGS_BOT_LOGIN_SECRET: str | None = None
    # The first agent's Google Calendar, by its "Secret address in iCal
    # format" (Settings > the calendar > Integrate calendar); another
    # agent's is kept under ``<this>__<NAME>``.
    MEETINGS_BOT_CALENDAR_SECRET: str | None = None
    # A folder to keep each meeting's audio in, one WAV per speaker under the
    # meeting's id (``meetings.audio``); unset, the audio is heard, not kept.
    MEETINGS_KEEP_AUDIO_DIR: Annotated[
        str | None,
        Configurable(
            OWNER, "Folder each meeting's audio is kept in, a file per speaker"
        ),
    ] = None
    # Whether each agent is sent into the meetings on its calendar as they
    # start (``domains.calendar``); off, the calendars are still read and
    # shown.
    MEETINGS_JOIN_FROM_CALENDAR: Annotated[
        bool,
        Configurable(
            OWNER, "Agents join the meetings on their calendars as they start"
        ),
    ] = True
