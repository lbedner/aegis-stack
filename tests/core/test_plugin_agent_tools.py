"""Declaring a tool is what grants it — and the effect is a decision.

A plugin's ``tools.py`` is discovered by convention and registers through
``register_tool``, but nothing told the agent about it: the default agent's
``tool_names`` was a static tuple, and the project's own
``tests/core/test_tools.py`` held ``EXPECTED_EFFECTS`` as a static dict in a
shared file, so a plugin that added a tool failed the suite it landed in.

Now the plugin declares ``AgentToolWiring(name, effect)`` and the
declaration travels: the agent's grants and the MCP grant list both read
it, and ``EXPECTED_EFFECTS`` gains the plugin's entries from the answers.
A registered-but-undeclared tool stays ungraded, and the suite still fails
it — an effect nobody decided is not a fact to infer.
"""

from __future__ import annotations

from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path
from aegis.core.plugins.composer import serialize_plugin_to_answer
from aegis.core.plugins.spec import (
    AgentToolWiring,
    PluginKind,
    PluginSpec,
    PluginWiring,
)

SLUG = "{{ project_slug }}"


def render(rel: str, **answers: Any) -> str:
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    context = {**get_copier_defaults(), "project_slug": "demo", **answers}
    return env.get_template(f"{SLUG}/{rel}.jinja").render(context)


def plugin_answer(*tools: tuple[str, str]) -> dict[str, Any]:
    spec = PluginSpec(
        name="media",
        kind=PluginKind.SERVICE,
        description="d",
        wiring=PluginWiring(
            agent_tools=[AgentToolWiring(name, effect) for name, effect in tools]
        ),
    )
    return serialize_plugin_to_answer(spec)


class TestSpec:
    def test_a_tool_declares_its_effect(self) -> None:
        spec = PluginSpec(
            name="media",
            kind=PluginKind.SERVICE,
            description="d",
            wiring=PluginWiring(agent_tools=[AgentToolWiring("thumbnail", "read")]),
        )

        assert spec.wiring.agent_tools[0].effect == "read"

    @pytest.mark.parametrize("effect", ["maybe", "READ", "", "delete"])
    def test_an_unknown_effect_is_refused(self, effect: str) -> None:
        with pytest.raises(ValueError, match="effect"):
            PluginSpec(
                name="media",
                kind=PluginKind.SERVICE,
                description="d",
                wiring=PluginWiring(agent_tools=[AgentToolWiring("thumbnail", effect)]),
            )

    def test_no_tools_is_the_default(self) -> None:
        spec = PluginSpec(name="x", kind=PluginKind.SERVICE, description="d")

        assert spec.wiring.agent_tools == []

    def test_the_answer_carries_the_declaration(self) -> None:
        answer = plugin_answer(("echo", "read"))

        assert answer["wiring"]["agent_tools"] == [{"name": "echo", "effect": "read"}]


class TestAgentGrants:
    def test_the_declared_tool_is_granted_to_the_agent(self) -> None:
        rendered = render(
            "app/services/ai/domains/chat/agent_loader.py",
            include_ai=True,
            _plugins=[plugin_answer(("echo", "read"))],
        )

        assert '"echo",' in rendered

    def test_an_undeclared_tool_is_never_granted(self) -> None:
        rendered = render(
            "app/services/ai/domains/chat/agent_loader.py", include_ai=True, _plugins=[]
        )

        assert '"echo",' not in rendered

    def test_mcp_tools_carry_the_declaration_too(self) -> None:
        rendered = render(
            "app/core/config.py",
            include_ai=True,
            include_mcp=True,
            _plugins=[plugin_answer(("echo", "read"))],
        )

        assert '"echo"' in rendered.split("MCP_TOOLS")[1].splitlines()[0]


class TestExpectedEffects:
    def test_the_declared_effect_lands_in_the_projects_suite(self) -> None:
        """The decision lives in the plugin's spec, not in a shared file."""
        rendered = render(
            "tests/core/test_tools.py", _plugins=[plugin_answer(("echo", "writes"))]
        )

        assert '"echo": "writes",' in rendered

    def test_the_in_tree_decisions_are_untouched(self) -> None:
        rendered = render("tests/core/test_tools.py", _plugins=[])

        assert '"ontology": "read",' in rendered
        assert '"save_memory": "writes",' in rendered


class TestOlderAnswers:
    def test_wiring_without_agent_tools_renders_as_before(self) -> None:
        """A project whose answers predate this key keeps working."""
        old = {
            "name": "media",
            "wiring": {"routers": [], "health_checks": []},
        }

        agent = render(
            "app/services/ai/domains/chat/agent_loader.py",
            include_ai=True,
            _plugins=[old],
        )
        suite = render("tests/core/test_tools.py", _plugins=[old])

        assert '"ontology": "read",' in suite
        assert "Traceback" not in agent
