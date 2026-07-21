"""build_chat_agent hydrates a working ToolChatAgent from an AgentConfig.

Lives in the chat_kit test package: hydration targets the pydantic-ai
loop, and this directory is what langchain-framework and memory-backend
stacks prune.
"""

from collections.abc import Generator
from dataclasses import dataclass

from pydantic_ai.models.test import TestModel
import pytest

from app.services.ai.agent_loader import AgentConfig, build_chat_agent
from app.services.ai.chat_kit import ChatScope, DoneFrame
from app.services.ai.tools import register_tool, unregister_tool


@dataclass
class _Deps:
    subject_id: int


def _config(**overrides: object) -> AgentConfig:
    data: dict[str, object] = {
        "slug": "assistant",
        "name": "Assistant",
        "system_prompt": "You are a test persona.",
        "model_id": None,
        "temperature": 0.3,
        "max_tokens": 256,
    }
    data.update(overrides)
    return AgentConfig(**data)  # type: ignore[arg-type]


async def _drain(agent: object, message: str) -> list[object]:
    return [
        f
        async for f in agent.stream_turn(  # type: ignore[attr-defined]
            scope=ChatScope(user_id="u1", surface="test"),
            deps=_Deps(1),
            message=message,
        )
    ]


@pytest.fixture
def registered_lookup() -> Generator[str]:
    async def lookup(key: str) -> str:
        """Look up a value for a key."""
        return f"val-{key}"

    register_tool("lookup", lookup)
    yield "lookup"
    unregister_tool("lookup")


async def test_config_tools_run_in_the_loop(registered_lookup: str) -> None:
    """An agent hydrated from config calls its DB-granted tools."""
    agent = build_chat_agent(
        _config(tool_names=(registered_lookup,)),
        model=TestModel(call_tools=[registered_lookup]),
        model_name="test-model",
        deps_type=_Deps,
        recorder=lambda **kwargs: 0.0,
    )

    frames = await _drain(agent, "q")

    done = frames[-1]
    assert isinstance(done, DoneFrame)
    assert done.tool_calls == 1


def test_module_scope_wires_a_context_provider() -> None:
    """An agent config with modules gets the module provider automatically."""
    from app.services.ai.module_context import MemoryModuleContextProvider

    agent = build_chat_agent(
        _config(memory_modules=("diet", "house-rules")),
        model=TestModel(custom_output_text="ok"),
        model_name="test-model",
        deps_type=_Deps,
        recorder=lambda **kwargs: 0.0,
    )

    providers = agent._providers  # noqa: SLF001 - wiring check, not behavior
    assert any(isinstance(p, MemoryModuleContextProvider) for p in providers)


def test_no_modules_means_no_module_provider() -> None:
    """Module-less agents keep a provider set identical to pre-port."""
    agent = build_chat_agent(
        _config(),
        model=TestModel(custom_output_text="ok"),
        model_name="test-model",
        deps_type=_Deps,
        recorder=lambda **kwargs: 0.0,
    )

    assert agent._providers == ()  # noqa: SLF001 - wiring check, not behavior


async def test_unknown_config_tool_degrades_to_a_working_agent() -> None:
    """A stale tool name in the DB must not break hydration or the turn."""
    agent = build_chat_agent(
        _config(tool_names=("ghost-tool",)),
        model=TestModel(custom_output_text="ok"),
        model_name="test-model",
        deps_type=_Deps,
        recorder=lambda **kwargs: 0.0,
    )

    frames = await _drain(agent, "q")

    done = frames[-1]
    assert isinstance(done, DoneFrame)
    assert done.answer == "ok"
