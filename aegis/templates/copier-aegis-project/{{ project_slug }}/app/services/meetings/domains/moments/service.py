"""Moments kept as the lines they are on are written, and read.

``seen`` runs on every flush of the bot's captions, inside the same
transaction: a detector failing is logged and skipped, never the line.
``find_again`` reads kept meetings over, for one held before a detector
was (or before it changed); ``tidy`` is the rest of looking a call over.
"""

from collections.abc import Callable, Iterable
from typing import TypeVar

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.log import logger
from app.services.meetings.domains.actions import runs as action_runs
from app.services.meetings.domains.actions import tokens
from app.services.meetings.domains.actions.prompt import excerpt_from
from app.services.meetings.domains.actions.registry import (
    ANSWERS,
    action_named,
    actions_for,
)
from app.services.meetings.domains.moments import queries
from app.services.meetings.domains.moments.detectors import (
    ADDRESSED,
    Before,
    Detector,
    Heard,
    detectors,
    title_of,
)
from app.services.meetings.domains.notes.queries import delete_in
from app.services.meetings.models import (
    ASKED,
    CLAIMED,
    DONE,
    GOING,
    IN_THE_APP,
    TONES,
    ActionChoice,
    Meeting,
    MeetingActionRun,
    MeetingMoment,
    MomentRecord,
    RunRecord,
)

# A moment of a kind said this soon after the first of a burst is on the
# same thing: a follow-up, a fragment, the same question asked again.
# Counted from the first, not the last, so bursts do not chain into one.
GAP_SECONDS = 90.0


async def seen(
    db: AsyncSession,
    meeting_id: int,
    lines: dict[int, str],
    before: dict[int, Before] | None = None,
) -> list[MeetingMoment]:
    """Every detector over ``lines`` (row id -> what was said so far): a
    moment found on a line is made, or its text follows the line. The line
    before each (``Before``) is the writer's, kept as it went (the bot's
    ``Transcript``), else read back. Returns the moments made now."""
    if not lines or not detectors():
        return []
    heard = await queries.hearing(db, [meeting_id])
    if before is None:
        before = await queries.before_in(db, [meeting_id])
    hits = _hits(
        heard(line_id, meeting_id, speaker, lines[line_id], is_me, before.get(line_id))
        for line_id, speaker, is_me in await queries.speakers(db, lines)
    )
    if not hits:  # most flushes: nothing to keep, so nothing more to read
        return []
    on = [line_id for line_id, _, _ in hits]
    kept = await queries.in_meetings(db, [meeting_id], on)
    return await _keep(db, hits, kept, {line_id: meeting_id for line_id in lines})


async def find_again(db: AsyncSession, meeting_ids: list[int]) -> None:
    """Every detector over these meetings' lines as they are now: a moment
    found is made, or follows its line, and one no longer found goes unless
    something was asked of it."""
    said = await queries.heard_in(db, meeting_ids)
    hits = _hits(heard for heard, _ in said)
    kept = await queries.in_meetings(db, meeting_ids)
    await _keep(db, hits, kept, {heard.line_id: m for heard, m in said})
    found = {(line_id, kind) for line_id, kind, _ in hits}
    await drop_unasked(db, [m.id or 0 for key, m in kept.items() if key not in found])
    await db.commit()


async def drop_unasked(db: AsyncSession, moment_ids: list[int]) -> None:
    """Delete these moments, but those something was asked of: their
    answers stay. The caller commits."""
    asked = {run.moment_id for run in await queries.runs_of(db, moment_ids)}
    await delete_in(db, MeetingMoment.id, [m for m in moment_ids if m not in asked])


def _hits(heard: Iterable[Heard]) -> list[tuple[int, str, str]]:
    """Each line a detector finds a moment on, as line id, kind and text."""
    found = detectors()
    return [
        (line.line_id, kind, text)
        for line in heard
        for kind, detect in found.items()
        if (text := _detected(kind, detect, line)) is not None
    ]


async def _keep(
    db: AsyncSession,
    hits: list[tuple[int, str, str]],
    kept: dict[tuple[int, str], MeetingMoment],
    meeting_of: dict[int, int],
) -> list[MeetingMoment]:
    """Each hit as its moment: one already ``kept`` on its line follows the
    text, else a new one is made in its meeting. The moments made."""
    made: list[MeetingMoment] = []
    for line_id, kind, text in hits:
        moment = kept.get((line_id, kind))
        if moment is None:
            moment = MeetingMoment(
                meeting_id=meeting_of[line_id], line_id=line_id, kind=kind, text=text
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
    """A meeting's moments, in the order they were said: each burst of them
    on one thing (``bursts``) under its first, which its actions and runs
    are of. ``said`` is the call's lines (speaker, line id, text), for the
    browser prompts: read here when the caller has not read them already."""
    found = await queries.of_meeting(db, meeting_id)
    if not found:
        return []
    meeting = await db.get_one(Meeting, meeting_id)
    asked = await _runs_of(
        db, [moment.id or 0 for moment, _, _ in found], meeting.owner_user_id
    )
    if said is None:
        said = await queries.said(db, meeting_id)
    return [_led(group, asked, said, meeting.url) for group in bursts(found)]


# A moment as ``queries.of_meeting`` finds it: with when, and by whom.
Found = tuple[MeetingMoment, float, str]


def bursts(found: list[Found], by_topic: bool = True) -> list[list[Found]]:
    """Moments (each with when and by whom, in the order said) in bursts: a
    moment said ``GAP_SECONDS`` or less after the first of its kind's open
    burst joins it (a follow-up, a fragment, the same thing asked again).
    One with a topic (the call cleaned up) joins its topic's, however far
    apart they were said, unless ``by_topic`` is off."""
    groups: list[list[Found]] = []
    open_by_kind: dict[str, list[Found]] = {}
    on_topic: dict[tuple[str, str], list[Found]] = {}
    for said in found:
        moment, at, _ = said
        if moment.kind == ADDRESSED:  # put to her by name: each is answered
            groups.append([said])
            continue
        if by_topic and moment.topic:
            key = (moment.kind, moment.topic.casefold())
            if key not in on_topic:
                on_topic[key] = []
                groups.append(on_topic[key])
            on_topic[key].append(said)
            continue
        burst = open_by_kind.get(moment.kind)
        if burst is not None and at - burst[0][1] <= GAP_SECONDS:
            burst.append(said)
            continue
        open_by_kind[moment.kind] = [said]
        groups.append(open_by_kind[moment.kind])
    return groups


async def cards_of(db: AsyncSession, meeting_id: int) -> dict[int, list[MeetingMoment]]:
    """Each of the meeting's moments' card (its burst, first to last), by
    moment id."""
    found = await queries.of_meeting(db, meeting_id)
    cards = [[moment for moment, _, _ in group] for group in bursts(found)]
    return {moment.id or 0: card for card in cards for moment in card}


async def ask(
    db: AsyncSession,
    meeting_id: int,
    moment_id: int,
    action: str,
    owner_user_id: int | None,
) -> MeetingActionRun:
    """Ask ``action`` of the burst the moment is in: a run on its first
    moment, framed from them all."""
    card = (await cards_of(db, meeting_id)).get(moment_id)
    return await _ask_card(db, meeting_id, card, moment_id, action, owner_user_id)


async def _ask_card(
    db: AsyncSession,
    meeting_id: int,
    card: list[MeetingMoment] | None,
    moment_id: int,
    action: str,
    owner_user_id: int | None,
) -> MeetingActionRun:
    """``action`` asked of ``card``'s first moment, framed from them all;
    of ``moment_id`` alone when it is on no card of the meeting's."""
    return await action_runs.ask(
        db,
        (card[0].id or 0) if card else moment_id,
        action,
        owner_user_id=owner_user_id,
        meeting_id=meeting_id,
        together=card[1:] if card else [],
    )


async def ask_for_new(db: AsyncSession, made: list[MeetingMoment]) -> None:
    """Ask, of each new moment's card, the action ``MEETINGS_AUTO_ACTIONS``
    names for its kind (``question=agent,mention=ticket``); none by default.
    The cards read once; a card two new moments share is asked once, and a
    follow-up said while its card is being answered is that run."""
    wanted = _auto_actions()
    if name := answerer():
        wanted[ADDRESSED] = name
    asks = [(m, wanted[m.kind]) for m in made if m.kind in wanted]
    if not asks:
        return
    # Every moment of one batch is the same meeting's (``seen``).
    meeting = await db.get_one(Meeting, asks[0][0].meeting_id)
    # A line put to the bot is a card of its own (``bursts``): no others read.
    alone = all(moment.kind == ADDRESSED for moment, _ in asks)
    cards = {} if alone else await cards_of(db, meeting.id or 0)
    asked: set[tuple[int, str]] = set()
    for moment, name in asks:
        card = cards.get(moment.id or 0)
        first = (card[0].id or 0) if card else moment.id or 0
        if (first, name) in asked:
            continue
        asked.add((first, name))
        try:
            await _ask_card(
                db, meeting.id or 0, card, moment.id or 0, name, meeting.owner_user_id
            )
        except action_runs.ActionNotFoundError:
            logger.warning("MEETINGS_AUTO_ACTIONS names no action", action=name)


def answerer() -> str | None:
    """The action that answers a line put to the bot by name, unasked: one
    ``MEETINGS_AUTO_ACTIONS`` names for it, else hers (``ANSWERS``) where
    the stack has her; None where nothing can (none registered, or one a
    person runs in their browser). The bot in the call waits on this one."""
    name = _auto_actions().get(ADDRESSED, ANSWERS)
    action = action_named(name)
    return name if action is not None and action.where != "browser" else None


def _auto_actions() -> dict[str, str]:
    pairs = (p.partition("=") for p in settings.MEETINGS_AUTO_ACTIONS.split(","))
    return {
        kind.strip(): name.strip()
        for kind, _, name in pairs
        if kind.strip() and name.strip()
    }


def _led(
    group: list[Found],
    asked: dict[int, list[RunRecord]],
    said: list[tuple[str, int, str]],
    link: str,
) -> MomentRecord:
    """A burst as its first moment's record: the runs of any of them, and
    each action framed from them all."""
    moments = [moment for moment, _, _ in group]
    runs = sorted(
        (r for m in moments for r in asked.get(m.id or 0, [])),
        key=lambda r: r.asked_at,
    )
    first, at, speaker = group[0]
    actions = [
        ActionChoice(
            name=a.name,
            label=a.label,
            where=a.where,
            prompt=(
                a.frame(excerpt_from(said, moments, link))
                if a.where == "browser"
                else None
            ),
            busy=any(r.action == a.name and r.status in GOING for r in runs),
        )
        for a in actions_for(first.kind)
    ]
    also = [_record(m, when, who) for m, when, who in group[1:]]
    return _record(first, at, speaker, actions, runs, also)


def _record(
    moment: MeetingMoment,
    at: float,
    speaker: str,
    actions: list[ActionChoice] | None = None,
    runs: list[RunRecord] | None = None,
    also: list[MomentRecord] | None = None,
) -> MomentRecord:
    return MomentRecord(
        id=moment.id or 0,
        meeting_id=moment.meeting_id,
        line_id=moment.line_id,
        kind=moment.kind,
        title=title_of(moment.kind),
        topic=moment.topic,
        text=moment.text,
        speaker=speaker,
        at=at,
        actions=actions or [],
        runs=runs or [],
        also=also or [],
    )


def answering(found: list[MomentRecord]) -> bool:
    """Whether an action asked of one of these moments is still running
    (one waiting on a runner while none is running is not)."""
    return any(r.going for m in found for r in m.runs)


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
    db: AsyncSession, moment_ids: list[int], owner_user_id: int | None
) -> dict[int, list[RunRecord]]:
    """Each moment's runs, oldest first; one asked of a runner is stalled
    (not going) while no runner of the owner's is running."""
    rows = await queries.runs_of(db, moment_ids)
    named = {run.id: action_named(run.action) for run in rows}
    where = {i: action.where if action else "" for i, action in named.items()}
    waiting = {r.id for r in rows if r.status == ASKED and where[r.id] == "runner"}
    listening = bool(waiting) and await tokens.listening(db, owner_user_id)
    runs: dict[int, list[RunRecord]] = {}
    for run in rows:
        action = named[run.id]
        stalled = run.id in waiting and not listening
        runs.setdefault(run.moment_id, []).append(
            RunRecord(
                id=run.id or 0,
                action=run.action,
                label=action.label if action else run.action,
                status=run.status,
                state=state_of(run.status, where[run.id], run.runner, stalled),
                going=run.status in GOING and not stalled,
                tone=TONES.get(run.status, "muted"),
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


def state_of(status: str, where: str, runner: str | None, stalled: bool) -> str:
    """Where a run stands, as both Overseers say it."""
    on = f" on {runner}" if runner and runner != IN_THE_APP else ""
    if stalled:
        return "No runner is running: start one with meetings runner"
    if status == ASKED:
        return "Waiting for a runner" if where == "runner" else "Asked"
    if status == CLAIMED:
        return f"Answering{on}…"
    return f"Answered{on}" if status == DONE else f"Failed{on}"
