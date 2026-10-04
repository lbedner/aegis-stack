"""The tool registry: what a model or an outside assistant may call.

It lives in core, so any service can register tools and an MCP server can
serve them without the AI service.
"""

import importlib
from pathlib import Path

import pytest

import app
from app.core.tools import (
    get_tool,
    mcp_servable,
    native_write_tool_names,
    register_tool,
    registered_tool_names,
    unregister_tool,
)


def _echo(text: str) -> str:
    """Echo the given text back."""
    return text


@pytest.mark.usefixtures("clean_registry")
class TestRegistration:
    def test_a_registered_tool_is_found_by_name(self) -> None:
        register_tool("echo", _echo, description="Echo a string", effect="read")

        tool = get_tool("echo")
        assert tool is not None
        assert (tool.func, tool.description) == (_echo, "Echo a string")
        assert "echo" in registered_tool_names()

    def test_duplicate_registration_is_an_error(self) -> None:
        register_tool("echo", _echo, effect="read")

        with pytest.raises(ValueError, match="already registered"):
            register_tool("echo", _echo, effect="read")

    def test_replace_allows_rebinding(self) -> None:
        def other(text: str) -> str:
            """Alternative echo."""
            return text.upper()

        register_tool("echo", _echo, effect="read")
        register_tool("echo", other, effect="read", replace=True)

        tool = get_tool("echo")
        assert tool is not None and tool.func is other

    def test_unregister_unknown_is_an_error(self) -> None:
        with pytest.raises(KeyError):
            unregister_tool("never-registered")


@pytest.mark.usefixtures("clean_registry")
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
    # A card shows what a script computed; it changes nothing.
    "draw_card": "read",
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
        if "register_tool(" in path.read_text():
            rel = path.relative_to(root.parent).with_suffix("")
            importlib.import_module(".".join(rel.parts))


def test_every_registered_app_tool_declares_its_expected_effect() -> None:
    # No ``clean_registry``: the sweep's imports register for good.
    _import_every_registrant()
    declared: dict[str, str | None] = {}
    for name in registered_tool_names():
        tool = get_tool(name)
        if tool is not None and tool.func.__module__.startswith("app."):
            declared[name] = tool.effect

    if not declared:
        pytest.skip("no service in this project registers tools")
    assert declared == {n: EXPECTED_EFFECTS.get(n) for n in declared}
