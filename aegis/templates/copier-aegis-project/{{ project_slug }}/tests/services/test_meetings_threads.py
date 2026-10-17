"""Commitments, contradictions and positions (``domains.threads``): kept
in each meeting's notes, read per meeting with the lines they cite, and
gathered per person across an owner's meetings (a commitment's ledger:
promised, raised again, done or not). Writing them is the notes' model
pass (``test_meetings_threads_notes``); here the notes are kept by hand."""

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.notes.service import notes_of
from app.services.meetings.domains.people.service import PeopleService
from app.services.meetings.domains.threads.service import (
    earlier,
    meeting_threads,
    person_threads,
)
from app.services.meetings.models import (
    Commitment,
    Contradiction,
    FollowUp,
    Notes,
    Position,
    ThreadSection,
)
from app.services.meetings.service import MeetingsService
from tests._meetings import ended, kept_guide


def _section(sections: list[ThreadSection], key: str) -> ThreadSection:
    return next(s for s in sections if s.key == key)


async def _deck(session: AsyncSession, owner: int | None) -> tuple[int, list[int]]:
    """A meeting where Ada promised Leonard the deck by Friday, held that
    a free tier is a mistake, and Leonard promised her the numbers."""
    return await ended(
        session,
        owner,
        ("Ada", "I'll send you the deck by Friday."),
        ("Ada", "A free tier would be a mistake."),
        ("Leonard", "I'll get you the numbers."),
        notes=lambda ids: Notes(
            summary="The deck.",
            commitments=[
                Commitment(
                    text="Send the deck",
                    owner="Ada",
                    to="Leonard",
                    due="Friday",
                    lines=[ids[0]],
                ),
                Commitment(
                    text="Get Ada the numbers",
                    owner="Leonard",
                    to="Ada",
                    lines=[ids[2]],
                ),
            ],
            positions=[
                Position(
                    text="Against a free tier",
                    speaker="Ada",
                    topic="Pricing",
                    lines=[ids[1]],
                )
            ],
        ),
    )


async def _commitments(session: AsyncSession, meeting_id: int) -> list[int]:
    """The ids of the meeting's commitments, in order."""
    notes = (await notes_of(session, [meeting_id]))[meeting_id].notes
    assert notes is not None
    return [c.id for c in notes.commitments if c.id is not None]


async def _sent(
    session: AsyncSession, owner: int | None, first: int, free_tier_line: int
) -> tuple[int, list[int]]:
    """A later meeting where Ada sent the deck (promised in ``first``) and
    came round to a free tier, against what she said before."""
    deck = (await _commitments(session, first))[0]
    return await ended(
        session,
        owner,
        ("Ada", "I sent the deck this morning."),
        ("Ada", "Let's do a free tier after all."),
        notes=lambda ids: Notes(
            summary="Sent.",
            follow_ups=[
                FollowUp(
                    text="Ada sent the deck",
                    commitment=deck,
                    status="done",
                    lines=[ids[0]],
                )
            ],
            contradictions=[
                Contradiction(
                    text="Now for a free tier, against it before",
                    speakers=["Ada"],
                    lines=[ids[1]],
                    against=[free_tier_line],
                )
            ],
            positions=[
                Position(
                    text="For a free tier",
                    speaker="Ada",
                    topic="Pricing",
                    shifted="Against one",
                    lines=[ids[1]],
                )
            ],
        ),
    )


async def test_a_persons_commitments_show_across_two_meetings(
    async_db_session: AsyncSession,
) -> None:
    first, said_first = await _deck(async_db_session, 1)
    second, said_second = await _sent(async_db_session, 1, first, said_first[1])

    sections = await person_threads(async_db_session, 1, "Ada")

    (deck,) = _section(sections, "promised").items
    assert (deck.text, deck.meeting_id, deck.status) == ("Send the deck", first, "done")
    assert "Leonard" in (deck.detail or "") and "Friday" in (deck.detail or "")
    assert [q.text for q in deck.quotes] == ["I'll send you the deck by Friday."]
    # Where it came up again: the later meeting's line.
    assert [(q.meeting_id, q.text) for q in deck.other] == [
        (second, "I sent the deck this morning.")
    ]
    (numbers,) = _section(sections, "promised_them").items
    assert (numbers.text, numbers.speaker, numbers.status) == (
        "Get Ada the numbers",
        "Leonard",
        "open",
    )
    stances = _section(sections, "positions").items
    assert [(p.meeting_id, p.text) for p in stances] == [
        (first, "Against a free tier"),
        (second, "For a free tier"),
    ]
    (both_ways,) = _section(sections, "contradictions").items
    assert [q.id for q in both_ways.quotes] == [said_second[1]]
    assert [q.id for q in both_ways.other] == [said_first[1]]


async def test_an_owner_gathers_only_their_own_meetings(
    async_db_session: AsyncSession,
) -> None:
    await _deck(async_db_session, 2)

    sections = await person_threads(async_db_session, 1, "Ada")

    assert all(not s.items for s in sections)


async def test_a_meeting_reads_its_threads_with_the_lines_they_cite(
    async_db_session: AsyncSession,
) -> None:
    first, said_first = await _deck(async_db_session, 1)
    second, said_second = await _sent(async_db_session, 1, first, said_first[1])

    sections = await meeting_threads(MeetingsService(async_db_session, 1), second)

    (raised,) = _section(sections, "follow_ups").items
    assert raised.status == "done"
    assert [q.text for q in raised.quotes] == ["I sent the deck this morning."]
    # The commitment it raises, as first said, in the earlier meeting.
    assert [q.text for q in raised.other] == ["I'll send you the deck by Friday."]
    (both_ways,) = _section(sections, "contradictions").items
    assert [q.text for q in both_ways.other] == ["A free tier would be a mistake."]
    (stance,) = _section(sections, "positions").items
    assert "Against one" in (stance.detail or "")
    assert not _section(sections, "commitments").items


async def test_notes_without_threads_read_with_none(
    async_db_session: AsyncSession,
) -> None:
    meeting_id, _ = await ended(
        async_db_session, 1, ("Ada", "Hello."), notes=lambda _: Notes(summary="Hi.")
    )

    sections = await meeting_threads(MeetingsService(async_db_session, 1), meeting_id)

    assert sections and all(not s.items for s in sections)


async def test_what_the_next_notes_are_written_with(
    async_db_session: AsyncSession,
) -> None:
    """The open commitments and the stances of the people in a meeting,
    from the owner's earlier ones, with the lines they rest on: what a
    follow-up may name and a contradiction may cite."""
    first, said_first = await _deck(async_db_session, 1)
    meeting = await MeetingsService(async_db_session, 1).request(
        "https://meet.google.com/xyz-abcd-efg"
    )

    context = await earlier(async_db_session, meeting, ["Ada"])

    # Numbered for the model, in order: [C1] is the deck.
    assert context.commitments == tuple(await _commitments(async_db_session, first))
    assert context.lines == set(said_first)
    assert "[C1] Ada: Send the deck" in context.text
    assert "Pricing" in context.text
    assert f"[{said_first[1]}] Ada: A free tier would be a mistake." in context.text


async def test_a_done_commitment_is_not_raised_again(
    async_db_session: AsyncSession,
) -> None:
    first, said_first = await _deck(async_db_session, 1)
    await _sent(async_db_session, 1, first, said_first[1])
    meeting = await MeetingsService(async_db_session, 1).request(
        "https://meet.google.com/xyz-abcd-efg"
    )

    context = await earlier(async_db_session, meeting, ["Ada"])

    deck = (await _commitments(async_db_session, first))[0]
    assert deck not in context.commitments
    # Ada's stance on pricing is her latest one.
    assert "For a free tier" in context.text
    assert "Against a free tier" not in context.text


async def test_a_first_meeting_is_written_with_nothing_earlier(
    async_db_session: AsyncSession,
) -> None:
    meeting = await MeetingsService(async_db_session, 1).request(
        "https://meet.google.com/xyz-abcd-efg"
    )

    context = await earlier(async_db_session, meeting, ["Ada"])

    assert (context.text, context.lines, context.commitments) == ("", set(), ())


async def test_a_persons_guide_reads_with_their_open_threads(
    async_db_session: AsyncSession,
) -> None:
    await _deck(async_db_session, 1)
    guide_id = await kept_guide(async_db_session, 1, "Ada")

    record = await PeopleService(async_db_session, 1).read(guide_id)

    (deck,) = _section(record.threads, "promised").items
    assert deck.text == "Send the deck"


async def test_a_meeting_with_no_owner_gathers_no_owners_meetings(
    async_db_session: AsyncSession,
) -> None:
    """No owner is the standalone install's one owner, not every owner."""
    await _deck(async_db_session, 1)

    sections = await person_threads(async_db_session, None, "Ada")

    assert all(not s.items for s in sections)
