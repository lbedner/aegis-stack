"""The actions taken on moments (``domains.actions``): each a run asked of
the runner component (``app.components.runner``), about a moment."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from pydantic import BaseModel

from app.components.runner.models import DONE, FAILED, RunnerRun
from app.core.figures import FIGURES

# How a run reads in both Overseers, by its status; any other is muted.
TONES = {DONE: "ok", FAILED: "error"}
# What claims a run of an action that runs in the app.
IN_THE_APP = "app"
# What a meetings run is about (its subject's kind): a moment, by its id.
MOMENT = "moment"


def subjects(moment_ids: Iterable[int]) -> list[str]:
    """These moments, as the subjects their runs are about."""
    return [str(moment_id) for moment_id in moment_ids]


def moment_of(run: RunnerRun) -> int:
    """The moment a meetings run is about."""
    return int(run.subject_id)


class ActionChoice(BaseModel):
    """An action a moment offers: its name, its button, and where it runs
    (``browser``, ``app`` or ``runner``)."""

    name: str
    label: str
    where: str
    # A browser action's prompt, to copy: it runs nowhere else.
    prompt: str | None = None
    # Asked of this moment already, and not yet back: not asked twice.
    busy: bool = False


class RunRecord(BaseModel):
    """One action asked of a moment: where it stands, and what it came back
    with."""

    id: int
    action: str
    label: str
    status: str
    # Where it stands, as the pages say it (``Answered on laptop``).
    state: str
    # Still going, and something is coming for it: the pages follow it.
    # One asked of a runner while none is running is not: nothing comes for
    # it until one starts.
    going: bool = False
    tone: str = "muted"  # ok, error or muted (``TONES``)
    result: str | None = None
    runner: str | None = None
    asked_at: datetime
    finished_at: datetime | None = None


class Going(BaseModel):
    """A run of the call's, as the bot's card lists it: its action, where it
    is (asked, claimed by ``runner``, or over), the question it answers
    (``moment``) and who asked it, and what it came back with, once over."""

    model_config = FIGURES

    id: int
    moment: int
    action: str
    status: str
    runner: str | None = None
    speaker: str
    text: str
    result: str | None = None


class LineAbout(BaseModel):
    """What a line of a call is about, as Illiana says it to the one who
    asked: her few words, and the card she drew of the part it names (its
    wiring), where it names one."""

    model_config = FIGURES

    summary: str
    card_id: str | None = None
