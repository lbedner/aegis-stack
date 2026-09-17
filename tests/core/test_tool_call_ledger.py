"""Every chat tool call is recorded (ported from aegis-pulse #223/#224).

``llm_usage`` records a turn: model, tokens, cost, duration. It cannot say
which tool ran inside it, which tools get reached for together, or how often
a turn spends its whole call budget and still answers short. An agent with a
couple of tools does not need that; an agent with twenty cannot be reasoned
about without it.

The seam is ``resolve_tools`` - every agent's callables pass through it. These
tests check the wiring is present in the template; the wrapper's runtime
behaviour is tested inside a generated project, in
``tests/services/ai/test_tool_call_ledger.py``.
"""

from __future__ import annotations

from typing import Any

from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"


def _source(path: str) -> str:
    return (get_template_path() / PROJECT_SLUG_PLACEHOLDER / path).read_text()


def _render(path: str, **overrides: Any) -> str:
    env = Environment(
        loader=FileSystemLoader(str(get_template_path())), keep_trailing_newline=True
    )
    ctx = {**get_copier_defaults(), "project_slug": "demo_app", **overrides}
    return env.get_template(f"{PROJECT_SLUG_PLACEHOLDER}/{path}").render(ctx)


class TestTheSeamIsUsed:
    def test_resolve_tools_wraps_every_callable(self) -> None:
        """Wrapping at the registry, not per tool: a tool added later is
        measured by existing rather than by remembering a decorator."""
        source = _source("app/services/ai/domains/chat/tools.py")

        assert "from app.services.ai.domains.chat.tool_telemetry import instrument" in (
            source
        )
        assert "instrument(entry.name, entry.func)" in source
        assert "resolved.append(entry.func)" not in source

    def test_the_turn_is_bound_where_the_model_is_called(self) -> None:
        """The kit is generic over a deps type it never inspects, so turn
        identity rides a context variable, set beside ``memory_user``."""
        source = _source("app/services/ai/domains/chat/chat_kit/agent.py")

        assert "tool_turn(" in source
        assert "from app.services.ai.domains.chat.tool_telemetry import tool_turn" in (
            source
        )

    def test_the_model_ships_and_is_exported(self) -> None:
        exports = _source("app/services/ai/models/agents/__init__.py")
        model = _source("app/services/ai/models/agents/agent_tool_call.py")

        assert "AgentToolCall" in exports
        assert '__tablename__ = "agent_tool_call"' in model
        # Ceiling hits are derived from the index, so nothing needs to know
        # the agent's tool-call limit at write time.
        assert "call_index" in model
        assert "turn_id" in model
