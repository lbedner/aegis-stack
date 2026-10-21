"""One person across an owner's meetings, and how to work with them: what
the model writes (``Guide``), the rows it is kept as, and the threads as
the pages show them (``domains.people``)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
from pydantic import Field as Described
from sqlalchemy import Index, Text
from sqlmodel import Field, SQLModel

from app.core.time import utcnow
from app.services.meetings.models.base import _OWNER_FK
from app.services.meetings.models.notes import NoteItem


class MeetingPerson(SQLModel, table=True):
    """One human across an owner's meetings: every participant a call named
    as them points here, so their guide, their threads and whether they are
    the owner ("me") follow them from call to call. A new name in a call is
    a new person until it is said to be someone already known."""

    __tablename__ = "meeting_person"
    __table_args__ = (Index("ix_meeting_person_owner_name", "owner_user_id", "name"),)

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(
        default=None,
        foreign_key=_OWNER_FK,
        ondelete="CASCADE",
        description="Whose meetings they are in; NULL on a project without auth",
    )
    name: str = Field(max_length=255, description="The name the calls first gave them")
    is_me: bool = Field(
        default=False,
        description="The owner themself: whose action items are theirs",
    )
    created_at: datetime = Field(default_factory=utcnow)


class Guide(BaseModel):
    """How to work with one person, as the model reads it from what they
    said across the owner's meetings: only how they work, each point citing
    the lines it rests on."""

    cares_about: list[NoteItem] = Described(
        default_factory=list, description="What they keep coming back to"
    )
    information: list[NoteItem] = Described(
        default_factory=list,
        description=(
            "How they like their information: big picture or detail, a demo "
            "or numbers, short or thorough"
        ),
    )
    decides: list[NoteItem] = Described(
        default_factory=list,
        description=(
            "How they decide and commit: a quick yes, needs to see it first, "
            "defers to someone, says they will and does or does not"
        ),
    )
    lands: list[NoteItem] = Described(
        default_factory=list,
        description="What lands with them and what gets pushback",
    )

    def points(self) -> list[NoteItem]:
        """Every point, part by part."""
        return [item for key in GUIDE_SECTIONS for item in getattr(self, key)]


# Each part of a guide, in the order the pages show them, with its heading.
GUIDE_SECTIONS = {
    "cares_about": "What they care about",
    "information": "How they like their information",
    "decides": "How they decide and commit",
    "lands": "What lands with them",
}


class PersonGuide(SQLModel, table=True):
    """How to work with one person, or why the model could not write it:
    its points are ``MeetingGuidePoint`` rows. Written again as meetings
    accrue; the owner's own note on them is kept across every rewrite, and
    a rewrite that fails keeps the points it had."""

    __tablename__ = "meeting_person_guide"

    id: int | None = Field(default=None, primary_key=True)
    person_id: int = Field(
        foreign_key="meeting_person.id", unique=True, ondelete="CASCADE"
    )
    error: str | None = Field(default=None, max_length=500)
    model_name: str | None = Field(default=None, max_length=255)
    meetings: int = Field(default=0, description="How many meetings it was read from")
    note: str | None = Field(
        default=None, max_length=2000, description="The owner's own note on them"
    )
    written_at: datetime = Field(default_factory=utcnow)


class MeetingGuidePoint(SQLModel, table=True):
    """One point of a guide, in its part (``section``, a ``Guide`` field)."""

    __tablename__ = "meeting_guide_point"
    __table_args__ = (
        Index("ix_meeting_guide_point_guide", "guide_id", "section", "ord"),
    )

    id: int | None = Field(default=None, primary_key=True)
    guide_id: int = Field(foreign_key="meeting_person_guide.id", ondelete="CASCADE")
    section: str = Field(max_length=32)
    ord: int
    text: str = Field(sa_type=Text)


class MeetingGuidePointLine(SQLModel, table=True):
    """A transcript line a guide's point rests on, in order."""

    __tablename__ = "meeting_guide_point_line"
    __table_args__ = (Index("ix_meeting_guide_point_line_line", "line_id"),)

    point_id: int = Field(
        foreign_key="meeting_guide_point.id", primary_key=True, ondelete="CASCADE"
    )
    line_id: int = Field(
        foreign_key="meeting_transcript_line.id", primary_key=True, ondelete="CASCADE"
    )
    ord: int


class Quote(BaseModel):
    """A transcript line a guide's point rests on."""

    id: int
    meeting_id: int
    speaker: str
    at: float
    text: str


class GuidePoint(BaseModel):
    text: str
    quotes: list[Quote]


class GuideSection(BaseModel):
    key: str
    title: str
    points: list[GuidePoint]


class ThreadItem(GuidePoint):
    """A commitment, follow-up, contradiction or position as the pages
    show it: in which meeting, whose, where it stands, the lines it cites
    (``quotes``) and its other lines (``other``: a contradiction's other
    side, where a commitment came up again or was first said)."""

    meeting_id: int
    speaker: str | None = None
    detail: str | None = None
    status: str | None = None
    other: list[Quote] = []


class ThreadSection(BaseModel):
    """One kind of thread, with what its other lines are (``other``)."""

    key: str
    title: str
    other: str | None = None
    empty: str = "Nothing yet."
    items: list[ThreadItem]


class GuideRow(BaseModel):
    """A guide with the person it is to and whose meetings they are in
    (``PeopleService.guides``)."""

    guide: PersonGuide
    person: str
    owner_user_id: int | None = None


class GuideRecord(GuideRow):
    """One person's guide read in full (``PeopleService.read``): each part
    with the lines its points rest on, their threads across the owner's
    meetings, and whether it can be written again now."""

    sections: list[GuideSection]
    writing: bool
    can_write: bool
    threads: list[ThreadSection] = []
