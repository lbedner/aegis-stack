"""One case added to a dataset without its YAML written by hand: what a
turn should do, said as fields (``NewCase``), kept by ``add_case``; or
drawn from a turn a person had (``from_turn``), its calls the checks to
start from and its script the one CI plays."""

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, StringConstraints
from pydantic_evals import Case
from pydantic_evals.evaluators import Contains, Evaluator
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.log import logger

from . import queries
from .datasets import (
    CaseInput,
    CaseMeta,
    DatasetSummary,
    EvalDataset,
    UnknownDatasetError,
    add,
    parse,
    text,
    written,
)
from .datasets import about as about_of
from .evaluators import AnswerAvoids, ToolCalls, call_counts
from .script import Step, recorded

# The most of a question a case drawn from it is named by.
NAME_CAP = 60
Said = Annotated[str, StringConstraints(min_length=1)]


class UnknownTurnError(LookupError, ValueError):
    """No assistant message of that id."""


class NewCase(BaseModel):
    """A case to add: the message a person asks, and what its turn should
    do. It checks something: a call made or never made, or what the answer
    says or leaves out."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: str = Field(description="The dataset it joins; a new one needs `about`")
    name: Said = Field(description="What the case is, in a few words; unique in its dataset")
    message: Said = Field(description="What the person asks")
    why: str | None = Field(default=None, description="What it guards against")
    agent: str | None = Field(default=None, description="The agent asked; the default when unset")
    calls: dict[Said, NonNegativeInt] = Field(
        default_factory=dict,
        description="Each tool the turn calls, and how many times; 0 for one it never calls",
    )
    says: list[str] = Field(default_factory=list, description="Text the answer contains")
    avoids: list[str] = Field(default_factory=list, description="Text the answer never says")
    script: list[Step] = Field(
        default_factory=list,
        description="The turn it expects, played without a model in CI",
    )
    about: str | None = Field(
        default=None, description="What a new dataset checks; unused for one there is"
    )


def calls_from(said: list[str]) -> dict[str, int]:
    """Calls as typed, each ``ledger`` (once), ``ledger=2`` or ``delete=0``
    (never). ValueError for no tool, or a count that is not one."""
    found: dict[str, int] = {}
    for one in said:
        tool, _, times = one.partition("=")
        if not tool.strip() or (times and not times.strip().isdigit()):
            raise ValueError(f"{one}: a tool, or tool=times (delete=0 for never)")
        found[tool.strip()] = int(times or 1)
    return found


def calls_typed(calls: dict[str, int]) -> list[str]:
    """``calls`` as ``calls_from`` reads them back."""
    return [f"{tool}={times}" for tool, times in calls.items()]


def checks(new: NewCase) -> list[Evaluator[Any, Any, Any]]:
    """What ``new`` passes on, as the evaluators a dataset keeps."""
    found: list[Evaluator[Any, Any, Any]] = [
        ToolCalls(tool=tool, times=times) for tool, times in new.calls.items()
    ]
    found.extend(Contains(value=text) for text in new.says)
    if new.avoids:
        found.append(AnswerAvoids(terms=new.avoids))
    return found


async def _dataset(session: AsyncSession, new: NewCase) -> tuple[EvalDataset, str]:
    """The dataset ``new`` joins and what it says it is: the one kept, or
    an empty one where ``new`` says what a new one checks."""
    try:
        kept = await text(session, new.dataset)
    except UnknownDatasetError:
        about = (new.about or "").strip()
        if not about:
            raise
        return EvalDataset(name=new.dataset, cases=[]), about
    return parse(new.dataset, kept), about_of(kept)


async def add_case(session: AsyncSession, new: NewCase) -> DatasetSummary:
    """Keep ``new`` as the last case of its dataset: the dataset, summed
    up. ``UnknownDatasetError`` for a dataset there is none of and nothing
    said of; ValueError for a name its dataset has, or a case that checks
    nothing."""
    passes_on = checks(new)
    if not passes_on:
        raise ValueError(f"Case {new.name!r} checks nothing: say calls, says or avoids")
    dataset, about = await _dataset(session, new)
    if any(case.name == new.name for case in dataset.cases):
        raise ValueError(f"Dataset {new.dataset!r} already has a case {new.name!r}")
    dataset.cases.append(
        Case(
            name=new.name,
            inputs=CaseInput(message=new.message, agent=new.agent, script=new.script),
            metadata=CaseMeta(why=new.why) if new.why else None,
            evaluators=tuple(passes_on),
        )
    )
    return await add(session, new.dataset, written(dataset, about), replace=True)


def _script(message_id: str, turn: queries.Turn) -> list[Step]:
    """The script the turn took; none (and said so) where its trace
    clipped a call."""
    try:
        return recorded(turn.trace, turn.answer)
    except ValueError as exc:
        logger.warning(f"Turn {message_id!r} drawn without its script: {exc}")
        return []


def drawn_as(drawn: NewCase, said: dict[str, Any]) -> NewCase:
    """``drawn`` with ``said`` over it, checked as a case said whole is."""
    return NewCase.model_validate(drawn.model_dump() | said)


async def from_turn(session: AsyncSession, message_id: str, dataset: str) -> NewCase:
    """The case assistant message ``message_id`` would be in ``dataset``:
    its question, named by it, each tool it called as many times, and the
    script it took. A start, for whoever keeps it to say what the turn
    should have done. ``UnknownTurnError`` for no such turn."""
    turn = await queries.turn(session, message_id)
    if turn is None:
        raise UnknownTurnError(f"No turn {message_id!r}")
    return NewCase(
        dataset=dataset,
        name=" ".join(turn.message.split())[:NAME_CAP],
        message=turn.message,
        calls=dict(call_counts(turn.trace)),
        script=_script(message_id, turn),
    )
