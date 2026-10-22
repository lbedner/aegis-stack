"""Meetings tables: a meeting the bot was asked to join, the Google account
it joined as (an agent), who was in it, and what each of them said.

A person is one human across an owner's meetings; a participant is that
person as one call named them. Transcript times are seconds from the
moment the bot joined. The notes are one model pass over the finished
transcript (where the stack has a model), each item a row citing the lines
it came from; so is each person's guide, how to work with them, read
across the owner's meetings, and what each series of meetings (one link,
met again and again) keeps coming back to. Every link between them is a foreign key:
deleting a meeting deletes what was kept of it, and a deleted line takes
its citations with it.

``Notes`` and ``Guide`` are what the model writes and what the pages read;
the rows are how they are kept (``domains.notes``, ``domains.people``).

One module per domain the tables belong to (``accounts``, ``actions``,
``calendar``, ``moments``, ``notes``, ``people``, ``series``), the meeting
itself (``meeting``), and what they all share (``base``). Importing this
package imports every table module, which is the point: a model never
imported is absent from ``SQLModel.metadata``, and alembic autogenerate
reads that metadata.
"""

# Search's SQLite tables, made beside these by every ``create_all``.
from app.services.meetings.domains.search import fts  # noqa: F401
from app.services.meetings.models.accounts import BotAccount
from app.services.meetings.models.actions import (
    ASKED,
    CLAIMED,
    DONE,
    FAILED,
    GOING,
    IN_THE_APP,
    TONES,
    ActionChoice,
    MeetingActionRun,
    MeetingRunnerToken,
    RunRecord,
)
from app.services.meetings.models.base import (
    IN_PROGRESS,
    LEAVABLE,
    NOT_DONE,
    STILL_WANTED,
    UNKNOWN,
    MeetingStatus,
    Platform,
)
from app.services.meetings.models.calendar import CalendarEvent
from app.services.meetings.models.meeting import (
    Caption,
    Meeting,
    MeetingParticipant,
    MeetingRecord,
    TranscriptLine,
    TranscriptRow,
)
from app.services.meetings.models.moments import MeetingMoment, MomentRecord
from app.services.meetings.models.notes import (
    ActionItem,
    Commitment,
    Contradiction,
    FollowUp,
    KeptNotes,
    MeetingNoteItem,
    MeetingNoteLine,
    MeetingNotes,
    NoteItem,
    Notes,
    Position,
)
from app.services.meetings.models.people import (
    GUIDE_SECTIONS,
    Guide,
    GuidePoint,
    GuideRecord,
    GuideRow,
    GuideSection,
    MeetingGuidePoint,
    MeetingGuidePointLine,
    MeetingPerson,
    PersonGuide,
    Quote,
    ThreadItem,
    ThreadSection,
)
from app.services.meetings.models.series import (
    OVER_TIME,
    MeetingSeries,
    MeetingTheme,
    MeetingThemeLine,
    SeriesNotes,
    SeriesRecord,
    SeriesRow,
    Theme,
)

__all__ = [
    "ASKED",
    "ActionChoice",
    "ActionItem",
    "BotAccount",
    "CLAIMED",
    "CalendarEvent",
    "Caption",
    "Commitment",
    "Contradiction",
    "DONE",
    "FAILED",
    "GOING",
    "FollowUp",
    "GUIDE_SECTIONS",
    "Guide",
    "GuidePoint",
    "GuideRecord",
    "GuideRow",
    "GuideSection",
    "IN_PROGRESS",
    "IN_THE_APP",
    "KeptNotes",
    "LEAVABLE",
    "Meeting",
    "MeetingActionRun",
    "MeetingGuidePoint",
    "MeetingGuidePointLine",
    "MeetingMoment",
    "MeetingNoteItem",
    "MeetingNoteLine",
    "MeetingNotes",
    "MeetingParticipant",
    "MeetingPerson",
    "MeetingRecord",
    "MeetingRunnerToken",
    "MeetingSeries",
    "MeetingStatus",
    "MeetingTheme",
    "MeetingThemeLine",
    "MomentRecord",
    "NOT_DONE",
    "NoteItem",
    "Notes",
    "OVER_TIME",
    "PersonGuide",
    "Platform",
    "Position",
    "Quote",
    "RunRecord",
    "STILL_WANTED",
    "SeriesNotes",
    "SeriesRecord",
    "SeriesRow",
    "TONES",
    "Theme",
    "ThreadItem",
    "ThreadSection",
    "TranscriptLine",
    "TranscriptRow",
    "UNKNOWN",
]
