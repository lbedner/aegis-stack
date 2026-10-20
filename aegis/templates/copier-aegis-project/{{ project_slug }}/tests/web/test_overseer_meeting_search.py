"""Overseer > Meetings' search box: every owner's transcripts and notes
searched for the admin, each hit opening its meeting in the drawer at the
line it is; the link Overseer's chat gives a hit opens it the same way."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.web_frontend import overseer_meetings
from app.services.meetings.domains.search.service import hit_link, search_meetings
from app.services.meetings.models import NoteItem, Notes
from app.services.system.models import ComponentStatus
from tests._meetings import THEIRS, ended
from tests.web.dom import none, one, select, text
from tests.web.overseer import page_html, sign_in, status_with

PAGE = overseer_meetings.PAGE
PARTIALS = overseer_meetings.PARTIALS
MEETINGS = ComponentStatus(name="meetings", message="Meetings ready")


@pytest.fixture
def overseer(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, async_client_with_db: TestClient
) -> TestClient:
    """Signed in as an admin, on the test's own session."""
    sign_in(app, monkeypatch, status_with(services=[MEETINGS]))
    return async_client_with_db


async def test_a_word_finds_every_owners_lines_and_notes(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    meeting_id, ids = await ended(
        async_db_session,
        THEIRS,
        ("Lawrence", "Our pricing is too low."),
        notes=lambda ids: Notes(
            summary="-", decisions=[NoteItem(text="Raise the pricing", lines=ids)]
        ),
    )

    html = page_html(overseer, f"{PAGE}?q=pricing")

    assert one(html, "#meetings-search input[name=q]").get("value") == "pricing"
    hits = select(html, "#meetings-search-hits [data-search-hit]")
    assert [text(one(hit, "[data-said]")) for hit in hits] == [
        "Raise the pricing",
        "Our pricing is too low.",
    ]
    assert "Decisions" in text(hits[0]) and "Lawrence" in text(hits[1])
    # Each opens its meeting at its line, the words kept above it.
    href = one(hits[1], "a").get("href") or ""
    assert f"meeting={meeting_id}" in href and f"line={ids[0]}" in href
    assert "q=pricing" in href


async def test_nothing_found_says_so(overseer: TestClient) -> None:
    html = page_html(overseer, f"{PAGE}?q=zeppelin")

    none(html, "#meetings-search-hits [data-search-hit]")
    assert "Nothing said" in text(one(html, "#meetings-search-hits"))


async def test_without_words_there_is_only_the_box(overseer: TestClient) -> None:
    html = page_html(overseer, PAGE)

    one(html, "#meetings-search input[name=q]")
    none(html, "#meetings-search-hits")


async def test_the_chats_link_opens_the_meeting_at_its_line(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    meeting_id, ids = await ended(
        async_db_session,
        THEIRS,
        ("Ada", "Hello."),
        ("Lawrence", "Pricing."),
        notes=lambda _: Notes(summary="-"),
    )
    (hit,) = await search_meetings(async_db_session, None, "pricing")

    page = page_html(overseer, hit_link(hit, overseer=True))
    drawer = one(page, "[data-drawer-sync]").get("data-drawer-url") or ""
    html = page_html(overseer, drawer)

    assert drawer == f"{PARTIALS}/{meeting_id}/drawer?line={ids[1]}"
    assert one(html, f"#line-{ids[1]}").get("data-hit") is not None
    assert one(html, f"#line-{ids[0]}").get("data-hit") is None
