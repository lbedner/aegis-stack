"""A secret read never waits on the write lock.

Every transaction begins IMMEDIATE (``app.core.db``): an open session is
the app's one write lock from its first statement, a SELECT included. The
secrets store opens a session of its own, so a read on a cold cache from
code that had queried its own session and not yet committed (a page that
read its own rows, then a key) waited the whole busy timeout behind
itself. A read takes no write lock at all (``read_only``), so it cannot
wait, whoever asks.
"""

from __future__ import annotations

import pytest

from app.components.secrets.store import DatabaseStore


@pytest.mark.usefixtures("holder")
async def test_a_read_inside_an_open_session_does_not_wait() -> None:
    assert await DatabaseStore().get_many(["RESEND_API_KEY"]) == {
        "RESEND_API_KEY": None
    }


@pytest.mark.usefixtures("holder")
async def test_the_overseer_listing_does_not_wait() -> None:
    assert await DatabaseStore().stored() == {}
