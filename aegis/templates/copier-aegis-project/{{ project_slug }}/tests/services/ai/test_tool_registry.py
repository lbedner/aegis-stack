"""Tests for the agent tool registry (name -> callable resolution)."""

from collections.abc import Generator
from unittest.mock import MagicMock

import pytest

from app.services.ai.tools import (
    register_tool,
    registered_tool_names,
    resolve_tools,
    unregister_tool,
)


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
        assert resolve_tools(["echo"]) == [_echo]

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
        assert resolve_tools(["echo"]) == [other]

    def test_unregister_unknown_is_an_error(self) -> None:
        with pytest.raises(KeyError):
            unregister_tool("never-registered")


class TestResolution:
    def test_unknown_name_is_skipped_with_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A DB row naming a missing callable degrades, never crashes."""
        import app.services.ai.tools as tools_module

        warned = MagicMock()
        monkeypatch.setattr(tools_module.logger, "warning", warned)
        register_tool("echo", _echo)

        resolved = resolve_tools(["echo", "missing-tool"])

        assert resolved == [_echo]
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

        assert resolve_tools(["first", "second"]) == [first, second]
