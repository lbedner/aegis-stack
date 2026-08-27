"""Stand-ins for the Flet runtime, for tests that drive real components.

Flet controls are plain Python objects; the only genuinely runtime
pieces are the page (session) and pointer events. A test that builds a
panel and calls ``_render()`` needs neither rendered - just something
shaped like them.
"""

from types import SimpleNamespace
from typing import Any


def tap(
    global_x: float = 600.0,
    global_y: float = 220.0,
    local_x: float = 0.0,
    local_y: float = 10.0,
) -> Any:
    """A pointer event: what ``on_tap_down`` handlers actually read."""
    return SimpleNamespace(
        global_x=global_x, global_y=global_y, local_x=local_x, local_y=local_y
    )


class FakePage:
    """Just enough page for a component test.

    Records what the component asked of the runtime instead of doing it:
    ``updates`` counts repaint requests, ``tasks`` collects the coroutines
    handed to ``run_task`` (call them yourself if the test wants the
    async work to actually happen).
    """

    def __init__(self) -> None:
        self.updates = 0
        self.tasks: list[Any] = []
        self.overlay: list[Any] = []

    def update(self, *controls: Any) -> None:
        self.updates += 1

    def run_task(self, handler: Any, *args: Any) -> None:
        self.tasks.append((handler, args))
