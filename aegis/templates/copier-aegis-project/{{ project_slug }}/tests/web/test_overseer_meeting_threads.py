"""Commitments, contradictions and positions in Overseer > Meetings: in a
meeting's drawer (loaded once its notes are there), each with the lines
it cites, and on a person's guide, their commitments across meetings."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.web_frontend import overseer_meetings
from app.services.meetings.domains.notes.service import notes_of
from app.services.meetings.models import Commitment, Contradiction, FollowUp, Notes
from app.services.system.models import ComponentStatus
from tests._meetings import ended, kept_guide
from tests.web.dom import none, one, select, text
from tests.web.overseer import page_html, sign_in, status_with

PARTIALS = overseer_meetings.PARTIALS
MEETINGS = ComponentStatus(name="meetings", message="Meetings ready")


@pytest.fixture
def overseer(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, async_client_with_db: TestClient
) -> TestClient:
    """Signed in as an admin, on the test's own session."""
    sign_in(app, monkeypatch, status_with(services=[MEETINGS]))
    return async_client_with_db


async def _two_meetings(session: AsyncSession) -> tuple[int, int]:
    """Ada promised the deck and held there is no budget; next time she
    sent it, and said there is budget after all."""
    first, before = await ended(
        session,
        4242,
        ("Ada", "I'll send the deck."),
        ("Ada", "There is no budget."),
        notes=lambda ids: Notes(
            summary="-",
            commitments=[Commitment(text="Send the deck", owner="Ada", lines=[ids[0]])],
        ),
    )
    made = (await notes_of(session, [first]))[first].notes
    assert made is not None
    deck = made.commitments[0].id
    second, _ = await ended(
        session,
        4242,
        ("Ada", "Sent it. We do have budget."),
        notes=lambda ids: Notes(
            summary="-",
            follow_ups=[
                FollowUp(text="Sent", commitment=deck, status="done", lines=ids)
            ],
            contradictions=[
                Contradiction(
                    text="Budget, then none",
                    speakers=["Ada"],
                    lines=ids,
                    against=[before[1]],
                )
            ],
        ),
    )
    return first, second


async def test_the_drawer_loads_the_meetings_threads_once_it_has_notes(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    first, second = await _two_meetings(async_db_session)
    drawer = page_html(overseer, f"{PARTIALS}/{second}/drawer")
    slot = one(drawer, "[data-threads]")
    assert slot.get("hx-get") == f"{PARTIALS}/{second}/threads"

    html = page_html(overseer, f"{PARTIALS}/{second}/threads")

    both = one(html, '[data-thread-section="contradictions"]')
    assert "Budget, then none" in text(both)
    against = text(one(both, "[data-other]"))
    assert "There is no budget." in against and f"Meeting {first}" in against
    raised = one(html, '[data-thread-section="follow_ups"]')
    assert "I'll send the deck." in text(raised)


async def test_a_meeting_without_notes_loads_no_threads(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    meeting_id, _ = await ended(
        async_db_session, 4242, ("Ada", "Hi."), notes=lambda _: Notes(summary="-")
    )
    html = page_html(overseer, f"{PARTIALS}/{meeting_id}/threads")

    assert select(html, "[data-thread-section]")
    assert "Nothing" in text(one(html, '[data-thread-section="commitments"]'))


async def test_a_persons_guide_shows_their_commitments_across_meetings(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    await _two_meetings(async_db_session)
    guide_id = await kept_guide(async_db_session, 4242, "Ada")

    html = page_html(overseer, f"{PARTIALS}/people/{guide_id}/drawer")

    promised = one(html, '[data-thread-section="promised"]')
    assert "Send the deck" in text(promised)
    assert "Done" in text(one(promised, "[data-status]"))
    assert "Sent it. We do have budget." in text(one(promised, "[data-other]"))
    none(html, '[data-thread-section="promised_them"] [data-thread]')
