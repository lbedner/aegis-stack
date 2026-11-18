"""The runner over HTTP: a runner on another machine, holding a token,
claims a run and posts its result; an owner makes, lists and revokes
runner tokens."""

from fastapi.testclient import TestClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.runner import tokens
from app.components.runner.models import RunnerToken
from app.core.tokens import digest
from tests._runner import asked

RUNS = "/api/v1/runner/runs"
TOKENS = "/api/v1/runner/tokens"


async def test_a_runner_with_a_token_claims_a_run_and_posts_its_result(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    run = await asked(async_db_session, owner_user_id=acting_owner_user_id)
    _, value = await tokens.create(async_db_session, acting_owner_user_id, "laptop")
    runner = {"Authorization": f"Bearer {value}"}
    want = {"actions": ["agent"]}

    refused = authenticated_client.post(
        f"{RUNS}/claim",
        json=want,
        headers={"Authorization": f"Bearer {tokens.PREFIX}nobody"},
    )
    claimed = authenticated_client.post(f"{RUNS}/claim", json=want, headers=runner)
    none_left = authenticated_client.post(f"{RUNS}/claim", json=want, headers=runner)
    finished = authenticated_client.post(
        f"{RUNS}/{run.id}/finish",
        json={"ok": True, "result": "It can."},
        headers=runner,
    )
    again = authenticated_client.post(
        f"{RUNS}/{run.id}/finish",
        json={"ok": True, "result": "Twice."},
        headers=runner,
    )

    assert refused.status_code == 401
    assert claimed.status_code == 200, claimed.text
    assert claimed.json() == {"id": run.id, "action": "agent", "prompt": run.prompt}
    assert none_left.status_code == 204
    assert finished.status_code == 200, finished.text
    assert finished.json()["status"] == "done"
    assert again.status_code == 404


async def test_a_runner_holding_a_token_from_before_the_component_is_let_in(
    authenticated_client: TestClient, async_db_session: AsyncSession
) -> None:
    """Meetings minted ``mrt_`` tokens; a token is found by its digest, so
    a runner still holding one keeps claiming."""
    async_db_session.add(
        RunnerToken(name="laptop", digest=digest("mrt_older"), hint="mrt_olde")
    )
    await async_db_session.commit()

    claimed = authenticated_client.post(
        f"{RUNS}/claim",
        json={"actions": ["agent"]},
        headers={"Authorization": "Bearer mrt_older"},
    )

    assert claimed.status_code == 204, claimed.text


async def test_an_owner_makes_lists_and_revokes_runner_tokens(
    authenticated_client: TestClient,
) -> None:
    made = authenticated_client.post(TOKENS, json={"name": "laptop"})
    listed = authenticated_client.get(TOKENS)
    revoked = authenticated_client.delete(f"{TOKENS}/{made.json()['id']}")

    assert made.status_code == 201, made.text
    assert made.json()["value"].startswith(tokens.PREFIX)
    assert [(t["name"], "value" in t) for t in listed.json()] == [("laptop", False)]
    assert revoked.status_code == 204
    assert authenticated_client.get(TOKENS).json() == []
