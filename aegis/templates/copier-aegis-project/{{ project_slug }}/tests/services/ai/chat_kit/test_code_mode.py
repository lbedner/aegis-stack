"""Code mode: capabilities plumb through the kit into the pydantic-ai Agent.

Lives in the chat_kit test package: capabilities target the pydantic-ai
loop, and this directory is what langchain-framework and memory-backend
stacks prune.
"""

from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel
import pytest

import app.services.ai.domains.chat.chat_kit.agent as kit_agent
from app.services.ai.domains.chat.agent_loader import AgentConfig, build_chat_agent
from app.services.ai.domains.chat.chat_kit import (
    ChatScope,
    DeltaFrame,
    DoneFrame,
    ErrorFrame,
    ToolChatAgent,
)
from app.services.ai.domains.chat.tools import register_tool, unregister_tool


@dataclass
class _Deps:
    subject_id: int


class _RecordingAgent:
    """Stands in for pydantic_ai.Agent; records constructor kwargs."""

    captured: dict[str, Any] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        type(self).captured = dict(kwargs)


class _FakeCapability:
    """Opaque capability object; the kit must not inspect it."""


@pytest.fixture
def recording_agent(monkeypatch: pytest.MonkeyPatch) -> Generator[type]:
    _RecordingAgent.captured = {}
    monkeypatch.setattr(kit_agent, "Agent", _RecordingAgent)
    yield _RecordingAgent


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


def test_kit_forwards_capabilities_to_the_agent(recording_agent: type) -> None:
    """Capabilities handed to the kit reach the pydantic-ai constructor."""
    cap = _FakeCapability()
    ToolChatAgent(
        model=TestModel(),
        model_name="test",
        instructions="persona",
        deps_type=_Deps,
        capabilities=[cap],
    )
    assert recording_agent.captured.get("capabilities") == [cap]


def test_kit_omits_capabilities_when_none_given(recording_agent: type) -> None:
    """No capabilities -> the kwarg is not sent at all (old-version safety)."""
    ToolChatAgent(
        model=TestModel(),
        model_name="test",
        instructions="persona",
        deps_type=_Deps,
    )
    assert "capabilities" not in recording_agent.captured


def test_build_chat_agent_forwards_capabilities(recording_agent: type) -> None:
    """The hydrator threads capabilities through to the kit."""
    cap = _FakeCapability()
    build_chat_agent(
        _config(),
        model=TestModel(),
        model_name="test",
        deps_type=_Deps,
        capabilities=[cap],
    )
    assert recording_agent.captured.get("capabilities") == [cap]


def _build(config: AgentConfig, **kwargs: Any) -> Any:
    return build_chat_agent(
        config,
        model=TestModel(),
        model_name="test",
        deps_type=_Deps,
        **kwargs,
    )


def test_code_mode_config_grants_scoped_code_execution(
    recording_agent: type,
) -> None:
    """A code_mode row yields a CodeMode capability scoped to granted tools."""
    _build(_config(code_mode=True, tool_names=("lookup", "quote")))

    caps = recording_agent.captured.get("capabilities")
    assert caps is not None and len(caps) == 1
    assert type(caps[0]).__name__ == "CodeMode"
    assert list(caps[0].tools) == ["lookup", "quote"]


def test_code_mode_raises_the_default_tool_call_budget(
    recording_agent: type,
) -> None:
    """The script -> observe -> script loop needs more turns than chat's 4."""
    kit = _build(_config(code_mode=True))

    assert kit._limits.tool_calls_limit == 16


def test_explicit_limit_wins_over_the_code_mode_default(
    recording_agent: type,
) -> None:
    kit = _build(_config(code_mode=True), tool_calls_limit=6)

    assert kit._limits.tool_calls_limit == 6


def test_plain_config_gets_no_capability_and_keeps_the_chat_budget(
    recording_agent: type,
) -> None:
    kit = _build(_config())

    assert "capabilities" not in recording_agent.captured
    assert kit._limits.tool_calls_limit == 4


# --- The live loop: scripts run in the sandbox, failures retry in-turn ----


@pytest.fixture
def registered_lookup() -> Generator[str]:
    async def lookup(key: str) -> str:
        """Look up a value for a key."""
        return f"val-{key}"

    register_tool("lookup", lookup, replace=True)
    yield "lookup"
    unregister_tool("lookup")


async def _drain(agent: ToolChatAgent[Any], message: str) -> list[Any]:
    return [
        frame
        async for frame in agent.stream_turn(
            scope=ChatScope(user_id="u1", surface="test"),
            deps=_Deps(1),
            message=message,
        )
    ]


BROKEN_SCRIPT = '{"code": "v = await lookup(key=+broken"}'
FIXED_SCRIPT = '{"code": "v = await lookup(key=\\"a\\")\\nv"}'


async def test_failing_script_recovers_inside_one_turn(
    registered_lookup: str,
) -> None:
    """Bad script -> traceback -> corrected script -> answer, one turn."""
    requests: list[int] = []

    async def scripted(messages: Any, info: AgentInfo) -> Any:
        requests.append(len(messages))
        if len(requests) == 1:
            yield {0: DeltaToolCall(name="run_code", json_args=BROKEN_SCRIPT)}
        elif len(requests) == 2:
            yield {0: DeltaToolCall(name="run_code", json_args=FIXED_SCRIPT)}
        else:
            yield "the value is "
            yield "val-a"

    recorded: list[dict[str, Any]] = []

    def recorder(**kwargs: Any) -> float:
        recorded.append(kwargs)
        return 0.0

    agent = build_chat_agent(
        _config(code_mode=True, tool_names=(registered_lookup,)),
        model=FunctionModel(stream_function=scripted),
        model_name="scripted",
        deps_type=_Deps,
        recorder=recorder,
    )

    frames = await _drain(agent, "look up a for me")

    assert isinstance(frames[-1], DoneFrame)
    assert frames[-1].answer == "the value is val-a"
    assert any(isinstance(f, DeltaFrame) for f in frames)
    assert len(requests) == 3  # broken script, fixed script, final answer
    assert len(recorded) == 1  # one usage row for the whole turn


async def test_unrecoverable_script_surfaces_an_error_frame(
    registered_lookup: str,
) -> None:
    """A model that never fixes its script ends in ErrorFrame, not a raise."""

    async def hopeless(messages: Any, info: AgentInfo) -> Any:
        yield {0: DeltaToolCall(name="run_code", json_args=BROKEN_SCRIPT)}

    agent = build_chat_agent(
        _config(code_mode=True, tool_names=(registered_lookup,)),
        model=FunctionModel(stream_function=hopeless),
        model_name="scripted",
        deps_type=_Deps,
        recorder=lambda **kwargs: 0.0,
    )

    frames = await _drain(agent, "look up a for me")

    assert isinstance(frames[-1], ErrorFrame)
