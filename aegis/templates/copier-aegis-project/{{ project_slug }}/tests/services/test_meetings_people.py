"""How to work with each person, as kept and read (``domains.people``):
one owner's guides, a guide read with the lines each point rests on, the
owner's own note on it, and the guide written again. Writing one is the
model's (``test_meetings_guides``); here the guides are kept by hand."""

from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.people import service as people_service
from app.services.meetings.domains.people.service import (
    GuideNotFoundError,
    PeopleService,
)
from app.services.meetings.models import NoteItem, Notes
from app.services.meetings.service import NothingToWriteError
from tests._meetings import ended, kept_guide


async def test_an_owner_sees_only_their_own_guides(
    async_db_session: AsyncSession,
) -> None:
    await kept_guide(async_db_session, 1, "Ada")
    graces = await kept_guide(async_db_session, 2, "Grace")

    mine = await PeopleService(async_db_session, 1).guides()
    every = await PeopleService(async_db_session, None).guides()

    assert [g.person for g in mine] == ["Ada"]
    assert sorted(g.person for g in every) == ["Ada", "Grace"]
    with pytest.raises(GuideNotFoundError):
        await PeopleService(async_db_session, 1).read(graces)


async def test_a_guide_reads_with_the_lines_each_point_rests_on(
    async_db_session: AsyncSession,
) -> None:
    meeting_id, ids = await ended(
        async_db_session,
        1,
        ("Ada", "Numbers first, then the story."),
        ("Leonard", "Sure."),
        notes=lambda _: Notes(summary="-"),
    )
    guide_id = await kept_guide(
        async_db_session,
        1,
        "Ada",
        information=[NoteItem(text="Wants the numbers first", lines=[ids[0]])],
    )

    record = await PeopleService(async_db_session, 1).read(guide_id)

    information = next(s for s in record.sections if s.key == "information")
    point = information.points[0]
    assert point.text == "Wants the numbers first"
    assert [(q.speaker, q.text, q.meeting_id) for q in point.quotes] == [
        ("Ada", "Numbers first, then the story.", meeting_id)
    ]
    assert [s.key for s in record.sections] == [
        "cares_about",
        "information",
        "decides",
        "lands",
    ]


async def test_the_owners_note_is_kept_and_an_empty_one_cleared(
    async_db_session: AsyncSession,
) -> None:
    guide_id = await kept_guide(async_db_session, 1, "Ada")
    svc = PeopleService(async_db_session, 1)

    kept = (await svc.set_note(guide_id, "  Prefers a call to an email.  ")).guide.note
    cleared = (await svc.set_note(guide_id, "   ")).guide.note

    assert kept == "Prefers a call to an email."
    assert cleared is None


async def test_a_guide_is_written_again_only_with_a_model_to_write_it(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    guide_id = await kept_guide(async_db_session, 1, "Ada")
    svc = PeopleService(async_db_session, 1)
    monkeypatch.setattr(people_service, "guide_writer", lambda: None)

    with pytest.raises(NothingToWriteError):
        await svc.write_again(guide_id)

    written: list[tuple[int | None, str]] = []
    runs: list[Any] = []

    async def write(owner: int | None, person: str) -> None:
        written.append((owner, person))

    monkeypatch.setattr(people_service, "guide_writer", lambda: write)
    monkeypatch.setattr(people_service, "background", runs.append)
    monkeypatch.setattr(people_service, "GUIDING", set())

    record = await svc.write_again(guide_id)
    for run in runs:
        await run

    assert record.writing and not record.can_write
    assert written == [(1, "Ada")]
