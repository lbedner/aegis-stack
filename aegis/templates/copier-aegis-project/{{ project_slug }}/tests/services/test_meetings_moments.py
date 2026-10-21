"""Moments: what is heard in a call that something can be done with. A
detector per kind reads each line as the bot writes it, and again as it
grows; the first kind is a question someone other than the owner asks."""

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.moments import detectors
from app.services.meetings.domains.moments.detectors import Heard, register_detector
from app.services.meetings.domains.moments.service import moments_of
from app.services.meetings.models import Caption
from app.services.meetings.service import MeetingsService, write_captions
from tests._meetings import MEET, said


async def _meeting(session: AsyncSession) -> int:
    meeting = await MeetingsService(session, None).request(MEET, "Notes")
    return meeting.id  # type: ignore[return-value]


async def test_a_question_someone_asks_is_a_moment(
    async_db_session: AsyncSession,
) -> None:
    meeting_id = await _meeting(async_db_session)

    lines = await said(
        async_db_session,
        meeting_id,
        ("Dana", "The report is late."),
        ("Dana", "Can we ship the CSV export this week?"),
    )

    (moment,) = await moments_of(async_db_session, meeting_id)
    assert moment.kind == "question"
    assert moment.line_id == lines[1]
    assert moment.speaker == "Dana"
    assert moment.text == "Can we ship the CSV export this week?"


async def test_the_owners_own_question_is_not(async_db_session: AsyncSession) -> None:
    meeting_id = await _meeting(async_db_session)
    await said(async_db_session, meeting_id, ("Sam", "Hi."))
    await MeetingsService(async_db_session, None).set_me(meeting_id, "Sam")

    await said(async_db_session, meeting_id, ("Sam", "Is everyone here?"))

    assert await moments_of(async_db_session, meeting_id) == []


async def test_a_line_that_grows_into_a_question_becomes_one_and_follows_it(
    async_db_session: AsyncSession,
) -> None:
    """A caption keeps growing while its speaker talks: the moment appears
    when the line turns into a question, and its text follows the line."""
    meeting_id = await _meeting(async_db_session)
    rows: dict[str, int] = {}

    async def caption(text: str, at: float) -> None:
        line = Caption("1", "Dana", text)
        await write_captions(async_db_session, meeting_id, [line], rows, at, {"1": 0.0})

    await caption("So the export", 1.0)
    assert await moments_of(async_db_session, meeting_id) == []
    await caption("So the export, can it ship?", 2.0)
    await caption("So the export, can it ship this week?", 3.0)

    (moment,) = await moments_of(async_db_session, meeting_id)
    assert moment.text == "So the export, can it ship this week?"


async def test_a_detector_registered_for_a_kind_finds_its_moments(
    async_db_session: AsyncSession,
) -> None:
    """Moments are not only questions: any kind a detector is registered
    for is found the same way."""
    register_detector(
        "mention",
        lambda heard: heard.text if "GridCo" in heard.text else None,
        replace=True,
    )
    try:
        meeting_id = await _meeting(async_db_session)
        await said(async_db_session, meeting_id, ("Tom", "GridCo moves to OAuth."))

        (moment,) = await moments_of(async_db_session, meeting_id)
        assert (moment.kind, moment.text) == ("mention", "GridCo moves to OAuth.")
    finally:
        detectors.unregister_detector("mention")


def test_what_a_detector_reads() -> None:
    """A detector sees one line: who said it, whether that is the owner,
    and what was said so far."""
    heard = Heard(line_id=1, speaker="Dana", text="Ready?", is_me=False)

    assert detectors.question(heard) == "Ready?"
    assert detectors.question(Heard(1, "Sam", "Ready?", is_me=True)) is None
    assert detectors.question(Heard(1, "Dana", "Ready.", is_me=False)) is None
