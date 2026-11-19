"""What the runner component's tests share, and the tests of what asks
runs of it."""

from importlib.util import find_spec
from itertools import count
from typing import Any
from uuid import uuid4

from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.runner import hooks, runs, tokens
from app.components.runner.models import RunnerRun

# What a test's runs are about: an issue, by where it is filed.
ISSUE = "issue"
# Where a test's agent works.
WHERE = "/code/app-worktrees/issue-12"


async def signed(db: AsyncSession, owner_user_id: int | None) -> dict[str, str]:
    """The headers of a runner holding a new token of the owner's."""
    _, value = await tokens.create(db, owner_user_id, "laptop")
    return {"Authorization": f"Bearer {value}"}


async def a_runner_looked_in(
    session: AsyncSession, owner_user_id: int | None = None
) -> None:
    """A runner has just asked for runs, so one is running: the owner's,
    or one for every owner."""
    _, value = await tokens.create(session, owner_user_id, "laptop")
    await tokens.resolve(session, value)


def step(tool: str, session: str = "0f0f", **on: Any) -> dict[str, Any]:
    """An agent's event as its hook posts it: ``tool`` about to run on
    ``on``, in ``session``, where a test's agent works."""
    return {
        "hook_event_name": hooks.TOOL,
        "session_id": session,
        "cwd": WHERE,
        "tool_name": tool,
        "tool_input": on,
    }


async def asked(
    db: AsyncSession, subject: str = "acme/app#12", **fields: Any
) -> RunnerRun:
    """A run asked of an agent about ``subject`` (an issue, nobody's), but
    for what ``fields`` say."""
    asking = {
        "owner_user_id": None,
        "kind": ISSUE,
        "action": "agent",
        "prompt": "Fix it.",
    }
    return await runs.ask(db, subject_id=subject, **{**asking, **fields})


def a_run(**fields: Any) -> RunnerRun:
    """A run as ``fields`` say it stands, put there rather than asked,
    claimed and finished: an agent's, about an issue, unless they say."""
    about = {"subject_kind": ISSUE, "subject_id": "acme/app#12"}
    return RunnerRun(**{**about, "action": "agent", "prompt": "Fix it."} | fields)


async def claimed(db: AsyncSession, run: RunnerRun, **runner: Any) -> RunnerRun:
    """``run`` (the oldest waiting, as a runner takes them), claimed."""
    taken = await runs.claim(db, None, ["agent"], runner="laptop", **runner)
    assert taken is not None and taken.id == run.id
    return taken


async def answered(
    db: AsyncSession,
    run: RunnerRun,
    result: str = "Done.",
    *,
    ok: bool = True,
    **said: Any,
) -> RunnerRun:
    """``run`` claimed and finished as ``result``, with what its agent said."""
    await claimed(db, run)
    return await runs.finish(
        db, run.id or 0, None, result, ok=ok, runner="laptop", **said
    )


# Owners where the stack has no users to make: any other number, each new.
_numbers = count(4242)


async def someone_else(session: AsyncSession) -> int:
    """An owner other than the one signed in, and than any made before: a
    user of their own where the stack has auth (a run's owner is one), any
    other number where it has not."""
    if find_spec("app.models.user") is None:
        return next(_numbers)
    from app.models.user import User

    user = User(email=f"someone.{uuid4().hex[:8]}@example.com", hashed_password="-")
    session.add(user)
    await session.flush()
    return user.id  # type: ignore[return-value]
