"""What the runner component's tests share, and the tests of what asks
runs of it."""

from importlib.util import find_spec
from itertools import count
from typing import Any
from uuid import uuid4

from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.runner import runs
from app.components.runner.models import RunnerRun

# What a test's runs are about: an issue, by where it is filed.
ISSUE = "issue"


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
