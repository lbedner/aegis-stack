"""A meeting's notes: what the model writes (``Notes``) and the rows they
are kept as (``domains.notes``)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from pydantic import Field as Described
from pydantic.json_schema import SkipJsonSchema
from sqlalchemy import Index, Text
from sqlmodel import Field, SQLModel

from app.core.time import utcnow


class NoteItem(BaseModel):
    # The row it is kept as; never asked of the model.
    id: SkipJsonSchema[int | None] = Described(default=None, exclude=True)
    text: str
    lines: list[int] = Described(
        default_factory=list, description="Ids of the transcript lines it came from"
    )


class ActionItem(NoteItem):
    owner: str | None = Described(
        default=None,
        description="The speaker who has to do it, named as in the transcript",
    )
    due: str | None = Described(default=None, description="When, if it was said")


class Commitment(ActionItem):
    """Someone said they would do something: ``owner`` will do ``text``,
    for ``to``, by ``due``."""

    to: str | None = Described(
        default=None,
        description="Who they said they would do it for, named as in the transcript",
    )


class FollowUp(NoteItem):
    """An earlier meeting's commitment raised again in this one. As the
    model writes it, ``commitment`` is the number it was shown; as kept and
    read, the commitment's own id (None once that commitment is gone)."""

    commitment: int | None = Described(
        description="The number in [C...] of the earlier commitment raised"
    )
    status: Literal["mentioned", "done", "dropped"] = Described(
        default="mentioned",
        description="Done, dropped, or only mentioned again and still open",
    )


class Contradiction(NoteItem):
    """Something said one way (``lines``) and the opposite way
    (``against``), by one person or two. As read, ``speakers`` are the
    people who said the lines on both sides."""

    speakers: list[str] = Described(
        default_factory=list,
        description="Who said the two things, named as in the transcript",
    )
    against: list[int] = Described(
        default_factory=list,
        description=(
            "Ids of the lines that say the opposite, in this meeting or an earlier one"
        ),
    )


class Position(NoteItem):
    """Where ``speaker`` stands (``text``) on ``topic``."""

    speaker: str = Described(description="Whose stance, named as in the transcript")
    topic: str
    shifted: str | None = Described(
        default=None, description="Where they stood before, when this is a change"
    )


class Notes(BaseModel):
    """What a meeting came to, as the model writes it and the pages read
    it. Notes kept before the threads (commitments onwards) read with
    none."""

    summary: str
    decisions: list[NoteItem] = []
    action_items: list[ActionItem] = []
    open_questions: list[NoteItem] = []
    # Described here as well as in the seeded prompt: a row seeded before
    # the threads keeps its old prompt, and this is what still reaches it.
    commitments: list[Commitment] = Described(
        default=[],
        description=(
            "Who said they would do what, for whom and by when, in their own words"
        ),
    )
    follow_ups: list[FollowUp] = Described(
        default=[],
        description=(
            "Each earlier commitment listed as [C...] that is raised again here:"
            " done, dropped, or only mentioned and still open"
        ),
    )
    contradictions: list[Contradiction] = Described(
        default=[],
        description=(
            "Something said one way and the opposite way, by one person or two,"
            " in this meeting or against an earlier line"
        ),
    )
    positions: list[Position] = Described(
        default=[],
        description=(
            "Where each person stands on the topics they spoke to, and where they"
            " stood before when it is a change"
        ),
    )

    def mine(self, me: set[str]) -> list[ActionItem]:
        """The action items one of ``me`` (the owner's names) has to do."""
        return [a for a in self.action_items if a.owner in me]


class MeetingNotes(SQLModel, table=True):
    """A meeting's notes as one model pass wrote them, or why it could not:
    the items themselves are ``MeetingNoteItem`` rows. Written again in
    place (a better model, a fixed transcript); a pass that fails keeps the
    items it had, with why."""

    __tablename__ = "meeting_notes"

    meeting_id: int = Field(
        foreign_key="meeting.id", primary_key=True, ondelete="CASCADE"
    )
    error: str | None = Field(default=None, max_length=500)
    model_name: str | None = Field(default=None, max_length=255)
    written_at: datetime = Field(default_factory=utcnow)


class MeetingNoteItem(SQLModel, table=True):
    """One item of a meeting's notes: its summary, a decision, an action
    item, an open question, or a thread (a commitment, a follow-up, a
    contradiction, a position). ``kind`` is the part of ``Notes`` it is in;
    the columns past ``text`` are the ones its kind has. A name the model
    gave is kept as written (``person_text``, ``to_text``) beside the
    person it was found to be, if anyone."""

    __tablename__ = "meeting_note_item"
    __table_args__ = (
        Index("ix_meeting_note_item_meeting", "meeting_id", "kind", "ord"),
        Index("ix_meeting_note_item_commitment", "commitment_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    meeting_id: int = Field(foreign_key="meeting.id", ondelete="CASCADE")
    kind: str = Field(max_length=32, description="The part of the notes it is in")
    ord: int = Field(description="Its place in its part")
    text: str = Field(sa_type=Text)
    person_id: int | None = Field(
        default=None,
        foreign_key="meeting_person.id",
        ondelete="SET NULL",
        description="Whose it is: an action's or commitment's owner, a position's speaker",
    )
    person_text: str | None = Field(
        default=None, max_length=255, description="That name as the model wrote it"
    )
    to_person_id: int | None = Field(
        default=None,
        foreign_key="meeting_person.id",
        ondelete="SET NULL",
        description="Who a commitment was made to",
    )
    to_text: str | None = Field(
        default=None, max_length=255, description="That name as the model wrote it"
    )
    due: str | None = Field(default=None, max_length=255)
    topic: str | None = Field(default=None, max_length=255)
    shifted: str | None = Field(default=None, sa_type=Text)
    status: str | None = Field(
        default=None,
        max_length=16,
        description="A follow-up's: mentioned, done, dropped",
    )
    commitment_id: int | None = Field(
        default=None,
        foreign_key="meeting_note_item.id",
        ondelete="SET NULL",
        description="The earlier commitment a follow-up raises",
    )


class MeetingNoteLine(SQLModel, table=True):
    """A transcript line a note item cites, in order; ``against``: the
    other side of a contradiction, which may be an earlier meeting's."""

    __tablename__ = "meeting_note_line"
    __table_args__ = (Index("ix_meeting_note_line_line", "line_id"),)

    item_id: int = Field(
        foreign_key="meeting_note_item.id", primary_key=True, ondelete="CASCADE"
    )
    line_id: int = Field(
        foreign_key="meeting_transcript_line.id", primary_key=True, ondelete="CASCADE"
    )
    against: bool = Field(default=False, primary_key=True)
    ord: int


class KeptNotes(BaseModel):
    """A meeting's notes read back from their rows (``notes_of``): what the
    last pass that worked wrote (None until one has), and why the last one
    failed, if it did."""

    notes: Notes | None
    error: str | None
    model_name: str | None
    written_at: datetime
