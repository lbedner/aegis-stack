"""An agent's tools: names resolved from the core registry.

The registry's own contract (registration, effects, what MCP may serve)
is tested in ``tests/core/test_tools.py``.

``resolve_tools`` hands back instrumented callables, not the registered
objects themselves: every call is wrapped for the tool-call ledger on the
way out. So resolution is asserted on what the wrapper wraps, which is also
what the model sees as the tool.
"""

from collections.abc import Callable
import inspect
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.core.tools import ADMIN_ONLY, Refused, acting_as, register_tool
from app.services.ai.domains.chat.tools import resolve_tools


def unwrapped(tools: list[Callable[..., Any]]) -> list[Callable[..., Any]]:
    """The callables under the ledger wrapper."""
    return [inspect.unwrap(tool) for tool in tools]


def first(text: str) -> str:
    """First tool."""
    return text


def second(text: str) -> str:
    """Second tool."""
    return text


@pytest.mark.usefixtures("clean_registry")
class TestResolution:
    def test_unknown_name_is_skipped_with_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A DB row naming a missing callable degrades, never crashes."""
        import app.services.ai.domains.chat.tools as tools_module

        warned = MagicMock()
        monkeypatch.setattr(tools_module.logger, "warning", warned)
        register_tool("first", first, effect="read")

        resolved = resolve_tools(["first", "missing-tool"])

        assert unwrapped(resolved) == [first]
        # The skip must be surfaced: a silently ignored tool row would be
        # undebuggable.
        warned.assert_called_once()
        assert warned.call_args.kwargs.get("tool_name") == "missing-tool"

    def test_resolution_preserves_order(self) -> None:
        register_tool("second", second, effect="read")
        register_tool("first", first, effect="read")

        assert unwrapped(resolve_tools(["first", "second"])) == [first, second]


async def peek() -> str:
    """An admin's tool."""
    return "the logs"


@pytest.mark.usefixtures("clean_registry")
async def test_an_admin_tool_answers_only_an_admin() -> None:
    """Chat checks a tool's ``admin`` as MCP does, at the call: an agent
    granted it serves whoever is chatting, admin or not."""
    register_tool("peek", peek, effect="read", admin=True)
    (tool,) = resolve_tools(["peek"])

    with acting_as(None, "assistant", admin=False):
        assert await tool() == Refused(error=ADMIN_ONLY)
    with acting_as(None, "assistant", admin=True):
        assert await tool() == "the logs"


async def strict(component: str) -> str:
    """A tool refusing an argument it does not know, naming the known."""
    raise ValueError(f"No component {component!r}; known: backend")


def strict_sync(component: str) -> str:
    """The same, not async."""
    raise ValueError(f"No component {component!r}; known: backend")


@pytest.mark.usefixtures("clean_registry")
async def test_a_refused_argument_is_the_models_to_correct() -> None:
    """A tool's ValueError is its answer, so the model asks again: raised,
    it ended a whole live call (2026-10-17, ``health("service:documents")``)."""
    register_tool("strict", strict, effect="read")
    register_tool("strict_sync", strict_sync, effect="read")
    tool, sync_tool = resolve_tools(["strict", "strict_sync"])

    told = Refused(error="ValueError: No component 'x'; known: backend")
    assert await tool(component="x") == told
    assert sync_tool(component="x") == told
