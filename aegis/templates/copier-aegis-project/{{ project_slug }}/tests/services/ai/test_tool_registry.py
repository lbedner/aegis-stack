"""Tests for the agent tool registry (name -> callable resolution).

``resolve_tools`` hands back instrumented callables, not the registered
objects themselves: every call is wrapped for the tool-call ledger on the
way out. So resolution is asserted on what the wrapper wraps, which is also
what the model sees as the tool.
"""

from collections.abc import Callable, Generator
import importlib
import inspect
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import app
from app.services.ai.domains.chat.tools import (
    get_tool,
    mcp_servable,
    native_write_tool_names,
    register_tool,
    registered_tool_names,
    resolve_tools,
    unregister_tool,
)


def unwrapped(tools: list[Callable[..., Any]]) -> list[Callable[..., Any]]:
    """The callables under the ledger wrapper."""
    return [inspect.unwrap(tool) for tool in tools]


@pytest.fixture(autouse=True)
def clean_registry() -> Generator[None]:
    """Remove tools registered by a test so cases stay independent."""
    before = set(registered_tool_names())
    yield
    for name in set(registered_tool_names()) - before:
        unregister_tool(name)


def _echo(text: str) -> str:
    """Echo the given text back."""
    return text


class TestRegistration:
    def test_register_and_resolve(self) -> None:
        register_tool("echo", _echo, description="Echo a string")

        assert "echo" in registered_tool_names()
        assert unwrapped(resolve_tools(["echo"])) == [_echo]

    def test_duplicate_registration_is_an_error(self) -> None:
        register_tool("echo", _echo)

        with pytest.raises(ValueError, match="already registered"):
            register_tool("echo", _echo)

    def test_replace_allows_rebinding(self) -> None:
        register_tool("echo", _echo)

        def other(text: str) -> str:
            """Alternative echo."""
            return text.upper()

        register_tool("echo", other, replace=True)
        assert unwrapped(resolve_tools(["echo"])) == [other]

    def test_unregister_unknown_is_an_error(self) -> None:
        with pytest.raises(KeyError):
            unregister_tool("never-registered")


class TestResolution:
    def test_unknown_name_is_skipped_with_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A DB row naming a missing callable degrades, never crashes."""
        import app.services.ai.domains.chat.tools as tools_module

        warned = MagicMock()
        monkeypatch.setattr(tools_module.logger, "warning", warned)
        register_tool("echo", _echo, effect="read")

        resolved = resolve_tools(["echo", "missing-tool"])

        assert unwrapped(resolved) == [_echo]
        # The skip must be surfaced: a silently ignored tool row would be
        # undebuggable.
        warned.assert_called_once()
        assert warned.call_args.kwargs.get("tool_name") == "missing-tool"

    def test_resolution_preserves_order(self) -> None:
        def first(text: str) -> str:
            """First tool."""
            return text

        def second(text: str) -> str:
            """Second tool."""
            return text

        register_tool("second", second)
        register_tool("first", first)

        assert unwrapped(resolve_tools(["first", "second"])) == [first, second]


class TestEffect:
    def test_a_tool_that_declares_no_effect_is_treated_as_a_write(self) -> None:
        """Default-deny: a write that forgets ``effect=`` must not run unseen
        in code mode or reach an outside assistant as a read."""
        register_tool("echo", _echo)

        tool = get_tool("echo")
        assert tool is not None
        assert tool.effect == "writes"
        assert "echo" in native_write_tool_names()
        assert mcp_servable(["echo"]) == []

    def test_rebinding_cannot_change_a_tools_effect(self) -> None:
        """A later import must not quietly turn ``propose`` into a read."""
        register_tool("echo", _echo, effect="proposes")

        with pytest.raises(ValueError, match="effect"):
            register_tool("echo", _echo, effect="read", replace=True)

    def test_every_non_read_effect_stays_native(self) -> None:
        register_tool("echo", _echo, effect="read")
        register_tool("file_it", _echo, effect="proposes")
        register_tool("save_it", _echo, effect="writes")

        native = native_write_tool_names()
        assert {"file_it", "save_it"} <= native
        assert "echo" not in native

    def test_mcp_never_serves_a_write_whatever_the_grant_says(self) -> None:
        register_tool("echo", _echo, effect="read")
        register_tool("file_it", _echo, effect="proposes")
        register_tool("save_it", _echo, effect="writes")

        granted = ["save_it", "echo", "file_it", "never-registered"]
        assert mcp_servable(granted) == ["echo", "file_it"]


# Every tool the app registers, by the effect it must declare. A tool
# registered from app code but missing here fails the test below, so each
# new tool's effect is a decision, not the (write) default.
EXPECTED_EFFECTS = {
    "context": "read",
    "record_reading": "writes",
    "save_memory": "writes",
    "replace_memory": "writes",
    # finance
    "ledger": "read",
    "accounts": "read",
    "quote": "read",
    "categories": "read",
    "bills": "read",
    "bill_candidates": "read",
    "tags": "read",
    # Reads the change types' contracts; files nothing.
    "change_types": "read",
    "propose": "proposes",
    "propose_many": "proposes",
    "pending": "proposes",
    "withdraw": "proposes",
    "withdraw_batch": "proposes",
}


def _import_every_registrant() -> None:
    """Import each app module that registers tools, so all are counted."""
    root = Path(app.__file__).parent
    for path in root.rglob("*.py"):
        if path.name != "tools.py" and "register_tool(" in path.read_text():
            rel = path.relative_to(root.parent).with_suffix("")
            importlib.import_module(".".join(rel.parts))


def test_every_registered_app_tool_declares_its_expected_effect() -> None:
    _import_every_registrant()
    declared: dict[str, str | None] = {}
    for name in registered_tool_names():
        tool = get_tool(name)
        if tool is not None and tool.func.__module__.startswith("app."):
            declared[name] = tool.effect

    assert declared, "no app tool registered; the import sweep found nothing"
    assert declared == {n: EXPECTED_EFFECTS.get(n) for n in declared}
