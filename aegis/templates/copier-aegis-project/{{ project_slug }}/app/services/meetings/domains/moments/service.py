"""Moments kept as the lines they are on are written, and read.

``seen`` runs on every flush of the bot's captions, inside the same
transaction: a detector failing is logged and skipped, never the line.
"""

from collections.abc import Callable
from typing import TypeVar

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.log import logger
from app.services.meetings.domains.actions.prompt import excerpt_from
from app.services.meetings.domains.actions.registry import action_named, actions_for
from app.services.meetings.domains.moments import queries
from app.services.meetings.domains.moments.detectors import (
    Detector,
    Heard,
    detectors,
    title_of,
)
from app.services.meetings.models import (
    ASKED,
    CLAIMED,
    DONE,
    IN_THE_APP,
    ActionChoice,
    Meeting,
    MeetingMoment,
    MomentRecord,
    RunRecord,
)


async def seen(
    db: AsyncSession, meeting_id: int, lines: dict[int, str]
) -> list[MeetingMoment]:
    """Every detector over ``lines`` (row id -> what was said so far): a
    moment found on a line is made, or its text follows the line. Returns
    the moments made now."""
    found = detectors()
    if not lines or not found:
        return []
    hits: list[tuple[int, str, str]] = []
    for line_id, speaker, is_me in await queries.speakers(db, lines):
        heard = Heard(line_id, speaker, lines[line_id], is_me)
        for kind, detect in found.items():
            text = _detected(kind, detect, heard)
            if text is not None:
                hits.append((line_id, kind, text))
    if not hits:  # most flushes: nothing to keep, so nothing more to read
        return []
    kept = await queries.on_lines(db, {line_id for line_id, _, _ in hits})
    made: list[MeetingMoment] = []
    for line_id, kind, text in hits:
        moment = kept.get((line_id, kind))
        if moment is None:
            moment = MeetingMoment(
                meeting_id=meeting_id, line_id=line_id, kind=kind, text=text
            )
            made.append(moment)
        moment.text = text
        db.add(moment)
    await db.flush()
    return made


async def moments_of(
    db: AsyncSession,
    meeting_id: int,
    said: list[tuple[str, int, str]] | None = None,
) -> list[MomentRecord]:
    """A meeting's moments, in the order they were said. ``said`` is the
    call's lines (speaker, line id, text), for the browser prompts: read
    here when the caller has not read them already."""
    found = await queries.of_meeting(db, meeting_id)
    if not found:
        return []
    runs = await _runs_of(db, [moment.id or 0 for moment, _, _ in found])
    if said is None:
        said = await queries.said(db, meeting_id)
    link = (await db.get_one(Meeting, meeting_id)).url
    return [
        MomentRecord(
            id=moment.id or 0,
            meeting_id=meeting_id,
            line_id=moment.line_id,
            kind=moment.kind,
            title=title_of(moment.kind),
            text=moment.text,
            speaker=speaker,
            at=at,
            actions=[
                ActionChoice(
                    name=a.name,
                    label=a.label,
                    where=a.where,
                    prompt=(
                        a.frame(excerpt_from(said, moment, link))
                        if a.where == "browser"
                        else None
                    ),
                )
                for a in actions_for(moment.kind)
            ],
            runs=runs.get(moment.id or 0, []),
        )
        for moment, at, speaker in found
    ]


def answering(found: list[MomentRecord]) -> bool:
    """Whether an action asked of one of these moments is still running."""
    return any(r.status in (ASKED, CLAIMED) for m in found for r in m.runs)


Item = TypeVar("Item")


def by_kind(found: list[Item], kind: Callable[[Item], str]) -> list[list[Item]]:
    """Moments grouped by their ``kind``, the kinds in the order first heard
    and each group in the order said: a tab or section per kind, on every
    surface that shows them."""
    groups: dict[str, list[Item]] = {}
    for item in found:
        groups.setdefault(kind(item), []).append(item)
    return list(groups.values())


async def _runs_of(
    db: AsyncSession, moment_ids: list[int]
) -> dict[int, list[RunRecord]]:
    """Each moment's runs, oldest first."""
    runs: dict[int, list[RunRecord]] = {}
    for run in await queries.runs_of(db, moment_ids):
        action = action_named(run.action)
        runs.setdefault(run.moment_id, []).append(
            RunRecord(
                id=run.id or 0,
                action=run.action,
                label=action.label if action else run.action,
                status=run.status,
                state=state_of(run.status, action.where if action else "", run.runner),
                result=run.result,
                runner=run.runner,
                asked_at=run.asked_at,
                finished_at=run.finished_at,
            )
        )
    return runs


def _detected(kind: str, detect: Detector, heard: Heard) -> str | None:
    try:
        return detect(heard)
    except Exception:
        logger.exception("Moment detector failed", kind=kind, line_id=heard.line_id)
        return None


def state_of(status: str, where: str, runner: str | None) -> str:
    """Where a run stands, as both Overseers say it."""
    on = f" on {runner}" if runner and runner != IN_THE_APP else ""
    if status == ASKED:
        return "Waiting for a runner" if where == "runner" else "Asked"
    if status == CLAIMED:
        return f"Answering{on}…"
    return f"Answered{on}" if status == DONE else f"Failed{on}"
