"""Moments and their actions over HTTP: an owner reads what a meeting's
call threw up, with what each offers, asks an action of one, and copies
its prompt; every owner's for Overseer's admin; and a runner on another
machine, holding a token, claims a run and posts its result (the runner
component's routes)."""

from importlib.util import find_spec
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.runner.protocol import RUNS
from tests._audit import as_admin, let_into_overseer
from tests._meetings import a_meeting, asked_a_question, said, someone_else
from tests._runner import signed

MEETINGS = "/api/v1/meetings"
ADMIN = "/api/v1/meetings/admin"


async def test_an_owner_reads_a_meetings_moments_and_what_each_offers(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    meeting_id, _ = await asked_a_question(async_db_session, acting_owner_user_id)

    response = authenticated_client.get(f"{MEETINGS}/{meeting_id}/moments")

    assert response.status_code == 200, response.text
    (moment,) = response.json()
    assert (moment["kind"], moment["speaker"]) == ("question", "Dana")
    assert {"copy", "agent"} <= {a["name"] for a in moment["actions"]}


async def test_an_owner_asks_illiana_what_a_line_is_about(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.components.backend.api.meetings import moments as api
    from app.services.meetings.models import LineAbout

    asked = AsyncMock(side_effect=[LineAbout(summary="The job runner."), None])
    monkeypatch.setattr(api, "line_about", asked)
    meeting_id = await a_meeting(async_db_session, acting_owner_user_id)
    (line,) = await said(async_db_session, meeting_id, ("Dana", "Move it to Redis."))
    here = f"{MEETINGS}/{meeting_id}/lines/{line}/about"

    answered = authenticated_client.post(f"{here}?part=component:scheduler")
    unanswered = authenticated_client.post(here)

    assert answered.status_code == 200, answered.text
    assert answered.json() == {"summary": "The job runner.", "card_id": None}
    assert unanswered.status_code == 404
    assert asked.await_args_list[0].args[1:] == (meeting_id, line)
    assert asked.await_args_list[0].kwargs == {"part": "component:scheduler"}
    assert asked.await_args_list[1].kwargs == {"part": None}


async def test_an_owner_asks_an_action_and_reads_the_prompt_to_copy(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    meeting_id, moment_id = await asked_a_question(
        async_db_session, acting_owner_user_id
    )
    here = f"{MEETINGS}/{meeting_id}/moments/{moment_id}"

    asked = authenticated_client.post(f"{here}/runs", json={"action": "agent"})
    unknown = authenticated_client.post(f"{here}/runs", json={"action": "nope"})

    assert asked.status_code == 202, asked.text
    assert (asked.json()["action"], asked.json()["status"]) == ("agent", "asked")
    assert unknown.status_code == 404
    (moment,) = authenticated_client.get(f"{MEETINGS}/{meeting_id}/moments").json()
    assert [r["status"] for r in moment["runs"]] == ["asked"]
    copy = next(a for a in moment["actions"] if a["name"] == "copy")
    assert "Can the CSV export ship this week?" in copy["prompt"]


@pytest.mark.skipif(
    find_spec("app.models.user") is None,
    reason="without auth every meeting is anyone's",
)
async def test_another_owners_moments_are_not_found(
    authenticated_client: TestClient, async_db_session: AsyncSession
) -> None:
    meeting_id, moment_id = await asked_a_question(
        async_db_session, await someone_else(async_db_session)
    )

    assert (
        authenticated_client.get(f"{MEETINGS}/{meeting_id}/moments").status_code == 404
    )
    asked = authenticated_client.post(
        f"{MEETINGS}/{meeting_id}/moments/{moment_id}/runs", json={"action": "agent"}
    )
    assert asked.status_code == 404


async def test_the_admin_reads_and_asks_every_owners(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    let_into_overseer(authenticated_client, monkeypatch)
    admin = as_admin(authenticated_client)
    meeting_id, moment_id = await asked_a_question(
        async_db_session, await someone_else(async_db_session)
    )

    read = admin.get(f"{ADMIN}/{meeting_id}/moments")
    asked = admin.post(
        f"{ADMIN}/{meeting_id}/moments/{moment_id}/runs", json={"action": "agent"}
    )

    assert read.status_code == 200, read.text
    assert asked.status_code == 202, asked.text


async def test_a_question_asked_of_an_agent_shows_what_a_runner_posts_back(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """Asked here, claimed and finished over the runner component's routes
    (theirs to test), the answer reads under its question."""
    meeting_id, moment_id = await asked_a_question(
        async_db_session, acting_owner_user_id
    )
    authenticated_client.post(
        f"{MEETINGS}/{meeting_id}/moments/{moment_id}/runs", json={"action": "agent"}
    )
    runner = await signed(async_db_session, acting_owner_user_id)

    claimed = authenticated_client.post(
        f"{RUNS}/claim", json={"actions": ["agent"]}, headers=runner
    )
    authenticated_client.post(
        f"{RUNS}/{claimed.json()['id']}/finish",
        json={"ok": True, "result": "It can."},
        headers=runner,
    )

    assert "CSV export" in claimed.json()["prompt"]
    (moment,) = authenticated_client.get(f"{MEETINGS}/{meeting_id}/moments").json()
    assert [(r["status"], r["result"], r["runner"]) for r in moment["runs"]] == [
        ("done", "It can.", "laptop")
    ]


async def test_an_owner_has_a_meeting_read_over_again(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Its call read over for moments: what it holds after."""
    from app.services.meetings.domains.moments import tidy

    monkeypatch.setattr(tidy, "cleaner", lambda: None)
    meeting_id, _ = await asked_a_question(async_db_session, acting_owner_user_id)

    found = authenticated_client.post(f"{MEETINGS}/{meeting_id}/moments/find")
    missing = authenticated_client.post(f"{MEETINGS}/0/moments/find")

    assert found.status_code == 200, found.text
    assert [m["kind"] for m in found.json()] == ["question"]
    assert missing.status_code == 404
