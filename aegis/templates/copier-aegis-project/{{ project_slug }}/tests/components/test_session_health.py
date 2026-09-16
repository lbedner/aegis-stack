"""The corruption detector matches Flet's desynced-tree signature and
nothing else - background loops key their terminate-vs-retry decision on it."""

import pytest

from app.components.frontend.core.session_health import (
    BOOT_ID,
    SessionLoops,
    is_tree_corruption,
    reload_if_server_restarted,
)

pytestmark = pytest.mark.asyncio


def test_matches_flet_tree_desync_signature() -> None:
    exc = AssertionError("_process_remove_command: control with ID 'None' not found.")
    assert is_tree_corruption(exc) is True


def test_ignores_other_errors() -> None:
    assert is_tree_corruption(AssertionError("something else")) is False
    assert is_tree_corruption(RuntimeError("_process_remove_command")) is False
    assert is_tree_corruption(ValueError("boom")) is False


class TestOneCorruptTreeStopsEveryLoop:
    """A page runs several loops; the tree they share is what breaks.

    The corruption handling lived in the dashboard refresh only. The
    worker-modal flush caught ``Exception`` and logged at debug - ten
    times a second - and the SSE listener reconnected every five seconds,
    both forever, because the liveness check could not save them: a
    session that reconnected across a webserver restart IS connected. Its
    control tree is the broken part.
    """

    def _loops(self, connected: bool = True) -> tuple[SessionLoops, list[str]]:
        nudges: list[str] = []

        class FakePage:
            def launch_url(self, url: str, **kwargs: object) -> None:
                nudges.append(url)

        return SessionLoops(FakePage(), lambda: connected), nudges

    async def test_corruption_is_fatal(self) -> None:
        loops, _ = self._loops()

        assert await loops.fatal(_corrupt()) is True

    async def test_an_ordinary_error_is_not(self) -> None:
        loops, _ = self._loops()

        assert await loops.fatal(RuntimeError("timeout")) is False

    async def test_the_other_loops_stop_even_though_the_page_reads_connected(
        self,
    ) -> None:
        """The exact incident: connected socket, unusable tree."""
        loops, _ = self._loops(connected=True)
        assert loops.alive() is True

        await loops.fatal(_corrupt())

        assert loops.alive() is False

    async def test_the_client_is_nudged_once_not_once_per_loop(self) -> None:
        loops, nudges = self._loops()

        await loops.fatal(_corrupt())
        await loops.fatal(_corrupt())
        await loops.fatal(_corrupt())

        assert nudges == ["/dashboard/"]


def _corrupt() -> AssertionError:
    return AssertionError("_process_remove_command: control with ID 'None' not found.")


class TestTheDisconnectGraceIsMeasuredInTime:
    """A grace counted in loop iterations means different things per loop:
    thirty checks was three seconds for the 0.1s flush and fifteen minutes
    for the 30s refresh, so the expensive loop bought the longest stay."""

    def _loops(self, connected: list[bool]) -> SessionLoops:
        state = {"connected": connected}

        def is_connected() -> bool:
            return state["connected"][0]

        return SessionLoops(object(), is_connected)

    def test_a_connected_page_is_alive(self) -> None:
        assert self._loops([True]).alive(now=0) is True

    def test_a_disconnect_is_tolerated_inside_the_window(self) -> None:
        loops = self._loops([False])

        assert loops.alive(now=0) is True
        assert loops.alive(now=29) is True

    def test_the_window_ends_on_time_not_on_iterations(self) -> None:
        loops = self._loops([False])
        loops.alive(now=0)

        assert loops.alive(now=31) is False

    def test_reconnecting_clears_the_window(self) -> None:
        flag = [False]
        loops = SessionLoops(object(), lambda: flag[0])
        loops.alive(now=0)

        flag[0] = True
        assert loops.alive(now=10) is True

        flag[0] = False
        assert loops.alive(now=35) is True


class TestATabThatPredatesThisProcess:
    """Catch the restart at connect, before anything touches the tree.

    The corruption is only detectable by provoking it: some later
    ``update()`` raises and the loops stop. A tab carrying a different
    boot id is the same condition one step earlier, where the cure is
    identical and nothing has failed yet.
    """

    class _Storage:
        def __init__(self, stored: str | None) -> None:
            self.stored = stored
            self.writes: list[str] = []

        async def get_async(self, key: str) -> str | None:
            return self.stored

        async def set_async(self, key: str, value: str) -> None:
            self.writes.append(value)
            self.stored = value

    class _Page:
        def __init__(self, stored: str | None) -> None:
            self.client_storage = TestATabThatPredatesThisProcess._Storage(stored)
            self.reloaded: list[str] = []

        def launch_url(self, url: str, **kwargs: object) -> None:
            self.reloaded.append(url)

    async def test_a_tab_from_a_previous_process_is_reloaded(self) -> None:
        page = self._Page(stored="a-boot-id-from-a-webserver-that-is-gone")

        assert await reload_if_server_restarted(page) is True
        assert page.reloaded == ["/dashboard/"]

    async def test_a_fresh_tab_is_stamped_and_left_alone(self) -> None:
        page = self._Page(stored=None)

        assert await reload_if_server_restarted(page) is False
        assert page.client_storage.writes == [BOOT_ID]
        assert page.reloaded == []

    async def test_a_tab_from_this_process_is_not_touched(self) -> None:
        """The common case: every reconnect within one process's lifetime."""
        page = self._Page(stored=BOOT_ID)

        assert await reload_if_server_restarted(page) is False
        assert page.client_storage.writes == []
        assert page.reloaded == []

    async def test_storage_failure_never_blocks_a_connect(self) -> None:
        """A check that cannot run degrades to the reactive path."""

        class Broken:
            async def get_async(self, key: str) -> str | None:
                raise RuntimeError("client storage unavailable")

        page = self._Page(stored=None)
        page.client_storage = Broken()

        assert await reload_if_server_restarted(page) is False
        assert page.reloaded == []
