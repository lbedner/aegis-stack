"""Looking a call over again (``look_over``): its moments read again
(``service.find_again``) once the bot is done with it, then, where the
stack has a model, its questions cleaned up (``clean``), the model's
verdicts kept (``keep_topics``). And which meetings a look-over over a
series, or every meeting, reads (``meeting_ids_of``).
"""

from collections.abc import Callable, Coroutine, Iterable
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.concurrency import background
from app.core.discovery import optional
from app.services.meetings.domains.moments import queries
from app.services.meetings.domains.moments.service import drop_unasked, find_again
from app.services.meetings.domains.series import queries as series_queries

# The model pass that cleans up a call's questions: only a stack with a
# model to ask (ai on pydantic-ai, with a database) has the module.
CLEAN = "app.services.meetings.domains.moments.clean"
# The meetings whose questions this process is cleaning up now.
CLEANING: set[int] = set()


async def meeting_ids_of(db: AsyncSession, series_id: int | None = None) -> list[int]:
    """Which meetings ``look_over`` reads over: every one, or a series' (its
    owner's, on its link). ``LookupError`` for a series there is not."""
    if series_id is None:
        return await queries.every_meeting_id(db)
    series = await series_queries.one_series(db, None, series_id)
    if series is None:
        raise LookupError(f"No series {series_id}")
    on_it = await series_queries.meetings_on(db, series.owner_user_id, series.link)
    return [m.id or 0 for m in on_it]


async def keep_topics(
    db: AsyncSession,
    cards: dict[int, list[int]],
    verdicts: Iterable[tuple[int, bool, str]],
) -> None:
    """A clean-up's verdict on each card (``cards``: its first moment's id
    -> every moment's in it): one kept takes the topic, one not goes unless
    something was asked of it. A verdict on a card there is not is left."""
    topics: dict[int, str] = {}
    dropped: list[int] = []
    for card, keep, topic in verdicts:
        moments = cards.get(card, [])
        if keep and topic.strip():
            topics.update(dict.fromkeys(moments, topic.strip()))
        elif not keep:
            dropped.extend(moments)
    await drop_unasked(db, dropped)
    for moment in await queries.by_ids(db, topics):
        moment.topic = topics[moment.id or 0]
        db.add(moment)
    await db.commit()


def cleaner() -> Callable[[int], Coroutine[Any, Any, None]] | None:
    """What cleans up a call's questions, where the stack has a model to."""
    return optional(CLEAN, "clean_up")


async def look_over(
    db: AsyncSession, meeting_ids: list[int], *, wait: bool = True
) -> None:
    """Read these meetings over again for moments (``find_again``), then
    clean up each one's questions where the stack has a model: one pass a
    meeting, awaited, or (not ``wait``: a page that follows it) in the
    background, ``CLEANING`` from now so the page's next read says so. A
    call the bot is still in is left: its moments are its own until then."""
    done = await queries.finished(db, meeting_ids)
    if not done:
        return
    await find_again(db, done)
    if (clean := cleaner()) is None:
        return
    for meeting_id in done:
        if wait:
            await clean(meeting_id)
        else:
            CLEANING.add(meeting_id)
            background(clean(meeting_id))
