"""How a meeting is kept: who was in it as people across meetings, its
notes and each person's guide as rows citing transcript lines, what the
bot heard of each of them, and which of them the owner is. Every link is a
foreign key, so deleting a meeting takes what cited it along."""

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.notes.service import (
    keep_failure,
    keep_notes,
    notes_of,
)
from app.services.meetings.domains.people.kept import keep_guide
from app.services.meetings.domains.people.participants import keep_heard
from app.services.meetings.domains.people.service import PeopleService
from app.services.meetings.models import (
    ActionItem,
    Commitment,
    Contradiction,
    FollowUp,
    Guide,
    MeetingGuidePoint,
    MeetingNoteItem,
    MeetingNoteLine,
    MeetingParticipant,
    MeetingPerson,
    NoteItem,
    Notes,
    PersonGuide,
    Position,
)
from app.services.meetings.service import MeetingsService
from tests._meetings import ended, guide_of, person_id


async def _people(session: AsyncSession) -> dict[int, str]:
    """Each participant's person, as participant id -> person name."""
    rows = await session.exec(
        select(MeetingParticipant.id, MeetingPerson.name).join(
            MeetingPerson, col(MeetingPerson.id) == MeetingParticipant.person_id
        )
    )
    return {participant: name for participant, name in rows.all()}


async def test_notes_are_kept_as_rows_and_read_back_as_written(
    async_db_session: AsyncSession,
) -> None:
    meeting_id, ids = await ended(
        async_db_session,
        1,
        ("Ada", "I'll send the deck to Grace by Friday."),
        ("Grace", "Then we ship in March."),
        ("Ada", "No, April."),
        notes=lambda ids: Notes(
            summary="Ship date.",
            decisions=[NoteItem(text="Ship in spring", lines=[ids[2], ids[1]])],
            action_items=[ActionItem(text="Send the deck", owner="Ada", due="Fri")],
            commitments=[
                Commitment(
                    text="Send the deck", owner="Ada", to="Grace", lines=[ids[0]]
                )
            ],
            contradictions=[
                Contradiction(text="March or April", lines=[ids[2]], against=[ids[1]])
            ],
            positions=[
                Position(text="April", speaker="Ada", topic="Ship", lines=[ids[2]])
            ],
        ),
    )

    kept = (await notes_of(async_db_session, [meeting_id]))[meeting_id]

    notes = kept.notes
    assert notes is not None
    assert notes.summary == "Ship date."
    # Citations keep their order.
    assert notes.decisions[0].lines == [ids[2], ids[1]]
    assert (notes.action_items[0].owner, notes.action_items[0].due) == ("Ada", "Fri")
    assert (notes.commitments[0].owner, notes.commitments[0].to) == ("Ada", "Grace")
    both = notes.contradictions[0]
    assert (both.lines, both.against) == ([ids[2]], [ids[1]])
    # Who said each side is read from the lines, not kept twice.
    assert both.speakers == ["Ada", "Grace"]
    assert notes.positions[0].speaker == "Ada"
    assert all(i.id is not None for i in [*notes.decisions, *notes.commitments])
    cited = (await async_db_session.exec(select(MeetingNoteLine))).all()
    assert len(cited) == 6


async def test_a_name_the_model_gave_points_at_its_person_or_stays_as_written(
    async_db_session: AsyncSession,
) -> None:
    meeting_id, _ = await ended(
        async_db_session,
        1,
        ("Ada", "I'll tell the board."),
        notes=lambda ids: Notes(
            summary="-",
            commitments=[
                Commitment(
                    text="Tell the board", owner=" ada ", to="the board", lines=ids
                )
            ],
        ),
    )

    item = (
        await async_db_session.exec(
            select(MeetingNoteItem).where(MeetingNoteItem.kind == "commitments")
        )
    ).one()
    read = (await notes_of(async_db_session, [meeting_id]))[meeting_id].notes

    assert item.person_id == await person_id(async_db_session, 1, "Ada")
    assert (item.to_person_id, item.to_text) == (None, "the board")
    assert read is not None
    assert (read.commitments[0].owner, read.commitments[0].to) == ("Ada", "the board")


async def test_one_name_is_one_person_across_an_owners_meetings_only(
    async_db_session: AsyncSession,
) -> None:
    for owner in (1, 1, 2):
        await ended(
            async_db_session, owner, ("Ada", "Hi."), notes=lambda _: Notes(summary="-")
        )

    people = (await async_db_session.exec(select(MeetingPerson))).all()

    assert sorted((p.owner_user_id, p.name) for p in people) == [(1, "Ada"), (2, "Ada")]
    assert set((await _people(async_db_session)).values()) == {"Ada"}


async def test_notes_written_again_keep_their_commitments_and_what_followed_them(
    async_db_session: AsyncSession,
) -> None:
    first, ids = await ended(
        async_db_session,
        1,
        ("Ada", "I'll send the deck."),
        ("Ada", "By Friday."),
        ("Grace", "And the budget?"),
        notes=lambda ids: Notes(
            summary="-",
            commitments=[Commitment(text="Send the deck", owner="Ada", lines=[ids[0]])],
        ),
    )
    made = (await notes_of(async_db_session, [first]))[first].notes
    assert made is not None
    commitment_id = made.commitments[0].id
    later, _ = await ended(
        async_db_session,
        1,
        ("Ada", "Sent it."),
        notes=lambda later_ids: Notes(
            summary="-",
            follow_ups=[
                FollowUp(
                    text="Sent",
                    commitment=commitment_id,
                    status="done",
                    lines=later_ids,
                )
            ],
        ),
    )

    # The same commitment, now citing one more line: the same row.
    await keep_notes(
        async_db_session,
        first,
        Notes(
            summary="Again.",
            commitments=[
                Commitment(text="Send the deck by Friday", owner="Ada", lines=ids[:2])
            ],
        ),
        "model",
    )
    again = await notes_of(async_db_session, [first, later])
    assert again[first].notes.commitments[0].id == commitment_id  # type: ignore[union-attr]
    assert again[later].notes.follow_ups[0].commitment == commitment_id  # type: ignore[union-attr]

    # A commitment that shares no line with it is another one.
    await keep_notes(
        async_db_session,
        first,
        Notes(summary="-", commitments=[Commitment(text="Other", lines=[ids[2]])]),
        "model",
    )
    gone = (await notes_of(async_db_session, [later]))[later].notes
    assert gone is not None
    assert gone.follow_ups[0].commitment is None


async def test_notes_that_fail_to_be_written_again_keep_the_ones_they_had(
    async_db_session: AsyncSession,
) -> None:
    meeting_id, _ = await ended(
        async_db_session, 1, ("Ada", "Hi."), notes=lambda _: Notes(summary="Kept.")
    )

    await keep_failure(async_db_session, meeting_id, "The model timed out")

    kept = (await notes_of(async_db_session, [meeting_id]))[meeting_id]
    assert kept.notes is not None
    assert (kept.notes.summary, kept.error) == ("Kept.", "The model timed out")


async def test_deleting_a_meeting_drops_what_cited_only_its_lines(
    async_db_session: AsyncSession,
) -> None:
    gone, old = await ended(
        async_db_session, 1, ("Ada", "March."), notes=lambda _: Notes(summary="-")
    )
    kept, new = await ended(
        async_db_session,
        1,
        ("Ada", "April."),
        notes=lambda new: Notes(
            summary="-",
            decisions=[NoteItem(text="April", lines=[new[0], old[0]])],
            contradictions=[
                Contradiction(text="March or April", lines=new, against=old)
            ],
        ),
    )
    ada = await person_id(async_db_session, 1, "Ada")
    await keep_guide(
        async_db_session,
        ada,
        Guide(
            decides=[
                NoteItem(text="Changes her mind", lines=old),
                NoteItem(text="Commits", lines=[*old, *new]),
            ]
        ),
        "model",
        meetings=2,
    )

    await MeetingsService(async_db_session, 1).delete(gone)

    notes = (await notes_of(async_db_session, [kept]))[kept].notes
    assert notes is not None
    assert notes.decisions[0].lines == [new[0]]
    # A contradiction with one side gone can no longer be checked.
    assert notes.contradictions == []
    guide = await guide_of(async_db_session, ada)
    assert guide is not None
    assert [(p.text, p.lines) for p in guide.decides] == [("Commits", new)]
    left = (await async_db_session.exec(select(MeetingNoteItem))).all()
    assert {i.meeting_id for i in left} == {kept}


async def test_what_the_bot_heard_is_kept_per_speaker(
    async_db_session: AsyncSession,
) -> None:
    meeting_id, _ = await ended(
        async_db_session,
        1,
        ("Ada", "Hi."),
        ("Grace", "Hello."),
        notes=lambda _: Notes(summary="-"),
    )

    await keep_heard(
        async_db_session, meeting_id, {"Ada": 4.0, "Grace": 2.5, "Unknown": 1.0}
    )

    record = await MeetingsService(async_db_session, 1).read(meeting_id)
    assert record.heard_seconds == {"Ada": 4.0, "Grace": 2.5, "Unknown": 1.0}
    assert record.meeting.unattributed_seconds == 1.0


async def test_who_the_owner_is_follows_them_into_their_next_meeting(
    async_db_session: AsyncSession,
) -> None:
    def ada_does_it(_: list[int]) -> Notes:
        return Notes(
            summary="-",
            action_items=[ActionItem(text="Write it", owner="Ada")],
        )

    first, _ = await ended(async_db_session, 1, ("Ada", "Mine."), notes=ada_does_it)
    second, _ = await ended(async_db_session, 1, ("Ada", "Mine."), notes=ada_does_it)
    svc = MeetingsService(async_db_session, 1)

    await svc.set_me(first, "Ada")
    record = await svc.read(second)
    assert (record.me, [a.text for a in record.mine]) == ("Ada", ["Write it"])

    await svc.set_me(second, None)
    assert (await svc.read(first)).me is None


async def test_a_guide_written_again_keeps_the_owners_note(
    async_db_session: AsyncSession,
) -> None:
    _, ids = await ended(
        async_db_session,
        1,
        ("Ada", "Numbers first."),
        notes=lambda _: Notes(summary="-"),
    )
    ada = await person_id(async_db_session, 1, "Ada")
    first = Guide(information=[NoteItem(text="Numbers first", lines=ids)])
    await keep_guide(async_db_session, ada, first, "model", meetings=1)
    row = (await async_db_session.exec(select(PersonGuide))).one()
    row.note = "Prefers a call."
    async_db_session.add(row)
    await async_db_session.commit()

    await keep_guide(
        async_db_session,
        ada,
        Guide(lands=[NoteItem(text="A demo", lines=ids)]),
        "model",
        meetings=1,
    )

    rows = (await async_db_session.exec(select(PersonGuide))).all()
    assert [(g.person_id, g.note) for g in rows] == [(ada, "Prefers a call.")]
    points = (await async_db_session.exec(select(MeetingGuidePoint))).all()
    assert [(p.section, p.text) for p in points] == [("lands", "A demo")]


async def test_picking_who_the_owner_is_in_a_meeting_unpicks_the_others(
    async_db_session: AsyncSession,
) -> None:
    meeting_id, _ = await ended(
        async_db_session,
        1,
        ("Ada", "Hi."),
        ("Leonard", "Hello."),
        notes=lambda _: Notes(summary="-"),
    )
    svc = MeetingsService(async_db_session, 1)

    await svc.set_me(meeting_id, "Ada")
    await svc.set_me(meeting_id, "Leonard")

    assert (await svc.read(meeting_id)).me == "Leonard"
    people = (await async_db_session.exec(select(MeetingPerson))).all()
    assert {p.name for p in people if p.is_me} == {"Leonard"}


async def test_a_caption_name_written_another_way_is_the_same_person(
    async_db_session: AsyncSession,
) -> None:
    for name in ("Ada Lovelace", "ada  lovelace"):
        await ended(
            async_db_session, 1, (name, "Hi."), notes=lambda _: Notes(summary="-")
        )

    people = (await async_db_session.exec(select(MeetingPerson))).all()

    assert [p.name for p in people] == ["Ada Lovelace"]


async def test_deleting_a_meeting_drops_who_spoke_only_there_and_their_guide(
    async_db_session: AsyncSession,
) -> None:
    gone, said = await ended(
        async_db_session,
        1,
        ("Ada", "Numbers first."),
        ("Grace", "Hi."),
        notes=lambda _: Notes(summary="-"),
    )
    await ended(
        async_db_session, 1, ("Grace", "Again."), notes=lambda _: Notes(summary="-")
    )
    ada = await person_id(async_db_session, 1, "Ada")
    guide = Guide(information=[NoteItem(text="Numbers first", lines=said[:1])])
    await keep_guide(async_db_session, ada, guide, "model", meetings=1)

    await MeetingsService(async_db_session, 1).delete(gone)

    people = (await async_db_session.exec(select(MeetingPerson))).all()
    assert [p.name for p in people] == ["Grace"]
    assert (await async_db_session.exec(select(PersonGuide))).all() == []


async def test_the_owners_own_guide_is_not_among_their_guides(
    async_db_session: AsyncSession,
) -> None:
    meeting_id, ids = await ended(
        async_db_session, 1, ("Ada", "Hi."), notes=lambda _: Notes(summary="-")
    )
    ada = await person_id(async_db_session, 1, "Ada")
    guide = Guide(information=[NoteItem(text="Says hi", lines=ids)])
    await keep_guide(async_db_session, ada, guide, "model", meetings=1)

    await MeetingsService(async_db_session, 1).set_me(meeting_id, "Ada")

    assert await PeopleService(async_db_session, 1).guides() == []
