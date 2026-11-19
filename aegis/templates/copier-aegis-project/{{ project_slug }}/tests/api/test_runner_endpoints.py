"""The runner over HTTP: a runner on another machine, holding a token,
claims a run and posts its result; an owner makes, lists and revokes
runner tokens."""

from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.runner import hooks, runs, tokens
from app.components.runner.models import RunnerToken
from app.components.runner.protocol import RUNS
from app.core.config import settings
from app.core.tokens import digest
from tests._runner import asked, signed, step

TOKENS = "/api/v1/runner/tokens"


async def test_a_runner_with_a_token_claims_a_run_and_posts_its_result(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    run = await asked(async_db_session, owner_user_id=acting_owner_user_id)
    runner = await signed(async_db_session, acting_owner_user_id)
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
    assert claimed.json()["id"] == run.id and claimed.json()["prompt"] == run.prompt
    assert none_left.status_code == 204
    assert finished.status_code == 200, finished.text
    assert finished.json()["status"] == "done"
    assert again.status_code == 404


async def test_a_runner_that_says_its_agent_marks_the_run_it_claims(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    run = await asked(async_db_session, owner_user_id=acting_owner_user_id)
    runner = await signed(async_db_session, acting_owner_user_id)

    authenticated_client.post(
        f"{RUNS}/claim", json={"actions": ["agent"], "agent": "claude"}, headers=runner
    )

    kept = await runs.one(async_db_session, run.id or 0)
    assert kept is not None and kept.agent == "claude"


async def test_a_run_on_a_branch_is_claimed_and_finished_as_work(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """The runner says where it keeps worktrees and how long it gives a
    command; the app hands it the branch and session, and takes back what
    the session has cost (kept as ``runs.finish`` keeps it)."""
    run = await asked(
        async_db_session,
        owner_user_id=acting_owner_user_id,
        branch="issue-12",
        session_id="0f0f",
    )
    runner = await signed(async_db_session, acting_owner_user_id)

    claimed = authenticated_client.post(
        f"{RUNS}/claim",
        json={"actions": ["agent"], "worktrees": "/w", "timeout": 3600},
        headers=runner,
    )
    finished = authenticated_client.post(
        f"{RUNS}/{run.id}/finish",
        json={"ok": True, "result": "Done.", "cost": 0.37, "worktree": "/w/issue-12"},
        headers=runner,
    )

    assert claimed.json() == {
        "id": run.id,
        "action": "agent",
        "prompt": run.prompt,
        "branch": "issue-12",
        "session_id": "0f0f",
        "resume": False,
    }
    assert finished.status_code == 200, finished.text
    await async_db_session.refresh(run)
    waited = run.overdue_at - run.claimed_at
    assert (run.status, run.cost, run.worktree) == ("done", 0.37, "/w/issue-12")
    assert round(waited.total_seconds()) == 7200


async def test_an_agents_hook_says_what_its_run_is_doing(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """The agent's own event, posted where its hooks post and signed with
    the runner's token: the run shows the step. An event that says nothing
    of what the agent is doing, or no token, changes nothing."""
    run = await asked(async_db_session, owner_user_id=acting_owner_user_id)
    runner = await signed(async_db_session, acting_owner_user_id)
    want = {"actions": ["agent"]}
    session = authenticated_client.post(
        f"{RUNS}/claim", json=want, headers=runner
    ).json()["session_id"]
    edit = step("Edit", session, file_path="/code/app-worktrees/issue-12/app/main.py")
    quiet = {
        **step("Read", session, file_path="/etc/hosts"),
        "hook_event_name": "Start",
    }

    noted = authenticated_client.post(hooks.PATH, json=edit, headers=runner)
    said_nothing = authenticated_client.post(hooks.PATH, json=quiet, headers=runner)
    unsigned = authenticated_client.post(
        hooks.PATH, json=edit, headers={"Authorization": ""}
    )

    assert [r.status_code for r in (noted, said_nothing, unsigned)] == [204, 204, 401]
    await async_db_session.refresh(run)
    assert run.activity == "Edit app/main.py"


async def test_an_agent_that_ends_its_turn_clears_what_its_run_was_doing(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    run = await asked(async_db_session, owner_user_id=acting_owner_user_id)
    runner = await signed(async_db_session, acting_owner_user_id)
    session = authenticated_client.post(
        f"{RUNS}/claim", json={"actions": ["agent"]}, headers=runner
    ).json()["session_id"]
    run.activity = "Bash make test"
    await async_db_session.commit()

    ended = authenticated_client.post(
        hooks.PATH,
        json={"hook_event_name": hooks.ENDED, "session_id": session},
        headers=runner,
    )

    assert ended.status_code == 204
    await async_db_session.refresh(run)
    assert run.activity is None


@pytest.mark.parametrize("timeout", [0, -5, 1e300, "NaN"])
async def test_a_runner_that_gives_a_command_no_real_time_is_refused(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
    timeout: object,
) -> None:
    """When a claimed run is given up on comes from this number: one that
    is no span of time is refused, not turned into a date."""
    runner = await signed(async_db_session, acting_owner_user_id)

    claimed = authenticated_client.post(
        f"{RUNS}/claim", json={"actions": ["agent"], "timeout": timeout}, headers=runner
    )

    assert claimed.status_code == 422


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
    token_maker: TestClient,
) -> None:
    maker = token_maker
    made = maker.post(TOKENS, json={"name": "laptop"})
    listed = maker.get(TOKENS)
    revoked = maker.delete(f"{TOKENS}/{made.json()['id']}")

    assert made.status_code == 201, made.text
    assert made.json()["value"].startswith(tokens.PREFIX)
    assert [(t["name"], "value" in t) for t in listed.json()] == [("laptop", False)]
    assert revoked.status_code == 204
    assert maker.get(TOKENS).json() == []


@pytest.mark.skipif(settings.AUTH_ENABLED, reason="with auth a token is its maker's")
def test_without_auth_only_the_operator_makes_or_revokes_a_token(
    async_client_with_db: TestClient,
) -> None:
    """A token for every owner's runs is an operator's to make: only where
    ``operator_refusal`` allows a change, as MCP's are. Listing is a read."""
    made = async_client_with_db.post(TOKENS, json={"name": "laptop"})
    revoked = async_client_with_db.delete(f"{TOKENS}/1")

    assert (made.status_code, revoked.status_code) == (403, 403)
    assert async_client_with_db.get(TOKENS).status_code == 200
