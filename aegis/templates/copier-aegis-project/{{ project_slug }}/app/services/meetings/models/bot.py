"""What the bot did on the meeting's page (``domains.bot.meet``): each
control it worked (joining, the captions, the chat, its mic, leaving) and
how, and why it left; so a change to Meet's page is a record on the
meeting, not only a log line."""

from datetime import datetime

from sqlalchemy import Text
from sqlmodel import Field, SQLModel

from app.core.time import utcnow

# The steps: each control it works, then why it left (``how`` is then the
# page's state, ``seen`` its text).
JOIN = "join"
CAPTIONS = "captions"
CHAT = "chat"
MIC = "mic"
LEAVE = "leave"
LEFT = "left"
# How a control was worked: by its label, by Meet's keyboard shortcut where
# the label was gone, already as wanted, or not at all.
LABEL = "label"
SHORTCUT = "shortcut"
ALREADY = "already"
MISSED = "missed"
# How each way reads on the meeting's page, and its tone: by its label is
# how it should go, so said by the step alone.
HOW_SAID = {SHORTCUT: "by shortcut", ALREADY: "already on", MISSED: "not found"}
HOW_TONES = {LABEL: "ok", ALREADY: "ok", SHORTCUT: "warn", MISSED: "error"}
# A step as the page took it, before it is kept on its meeting: the step,
# how, what the page showed, and when.
Took = tuple[str, str, str | None, datetime]


class MeetingBotStep(SQLModel, table=True):
    """One step the bot took on a meeting's page, kept the first time it
    went each way in the call (a control missed, then found, is two)."""

    __tablename__ = "meeting_bot_step"

    id: int | None = Field(default=None, primary_key=True)
    meeting_id: int = Field(foreign_key="meeting.id", ondelete="CASCADE", index=True)
    step: str = Field(max_length=16)
    how: str = Field(max_length=16)
    seen: str | None = Field(
        default=None,
        sa_type=Text,
        description="What the page showed where its label did not work: "
        "its buttons, as a reader hears them (or why it left, its text)",
    )
    at: datetime = Field(default_factory=utcnow)

    @property
    def said(self) -> str:
        """The step as the page shows it ("Chat · by shortcut")."""
        how = None if self.how == LABEL else HOW_SAID.get(self.how, self.how)
        return " · ".join(filter(None, (self.step.capitalize(), how)))

    @property
    def tone(self) -> str:
        return HOW_TONES.get(self.how, "muted")
