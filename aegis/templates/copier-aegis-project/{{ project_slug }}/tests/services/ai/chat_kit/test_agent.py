"""ToolChatAgent turn mechanics — streaming, context, tools, usage, errors.

The LLM never hits an API here: ``TestModel`` is the streaming-capable seam
(``FunctionModel`` needs a stream_function and is intentionally not used).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass

from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel

from app.services.ai.domains.chat.chat_kit import (
    ChatMessage,
    ChatScope,
    DeltaFrame,
    DoneFrame,
    ErrorFrame,
    StaticContextProvider,
    ToolChatAgent,
    compose_context,
    to_model_history,
)


class _BoomModel(TestModel):
    """A model whose streamed request fails cleanly (async CM that raises in
    ``__aenter__``), so we exercise the turn's error path without leaving an
    un-awaited coroutine warning."""

    def request_stream(self, *args, **kwargs):  # type: ignore[override]
        @asynccontextmanager
        async def _cm():
            raise RuntimeError("model exploded")
            yield  # unreachable; makes this an async generator

        return _cm()


@dataclass
class _Deps:
    subject_id: int


def _scope() -> ChatScope:
    return ChatScope(user_id="u1", surface="metrics")


def _agent(model: TestModel, **overrides):
    captured: dict = {}

    def recorder(*, action, model_name, usage, user_id):
        captured.update(
            action=action, model_name=model_name, usage=usage, user_id=user_id
        )
        return 0.0123

    agent = ToolChatAgent(
        model=model,
        model_name="claude-sonnet-5",
        instructions="You are a test persona.",
        deps_type=_Deps,
        action="chat:metrics",
        recorder=recorder,
        **overrides,
    )
    return agent, captured


async def _drain(agent, **kwargs):
    return [f async for f in agent.stream_turn(**kwargs)]


async def test_streams_deltas_then_done_with_answer() -> None:
    agent, _ = _agent(TestModel(custom_output_text="Downloads held steady."))
    frames = await _drain(
        agent, scope=_scope(), deps=_Deps(7), message="how are downloads?"
    )
    deltas = [f for f in frames if isinstance(f, DeltaFrame)]
    done = [f for f in frames if isinstance(f, DoneFrame)]
    assert len(done) == 1
    # The done frame is terminal (last) and carries the full answer.
    assert isinstance(frames[-1], DoneFrame)
    assert done[0].answer == "Downloads held steady."
    assert "".join(d.text for d in deltas) == "Downloads held steady."


async def test_records_usage_via_injected_recorder() -> None:
    agent, captured = _agent(TestModel(custom_output_text="ok"))
    frames = await _drain(agent, scope=_scope(), deps=_Deps(7), message="q")
    done = frames[-1]
    assert isinstance(done, DoneFrame)
    # Real token counts flow from the streaming result through the ledger path.
    assert done.usage["input_tokens"] > 0
    assert done.usage["output_tokens"] > 0
    assert done.cost_usd == 0.0123
    assert captured["action"] == "chat:metrics"
    assert captured["user_id"] == "u1"
    assert captured["usage"] == done.usage


def test_compose_context_wraps_blocks_as_reference_data() -> None:
    block = compose_context([("briefing", "TODAY: 42 downloads")])
    assert block is not None
    assert '<context name="briefing">' in block
    assert "TODAY: 42 downloads" in block
    # Nothing to add -> None, so the run carries no extra instructions block.
    assert compose_context([]) is None


async def test_context_provider_participates_in_a_turn() -> None:
    agent, _ = _agent(
        TestModel(custom_output_text="ok"),
        context_providers=[StaticContextProvider("briefing", "TODAY: 42 downloads")],
    )
    frames = await _drain(agent, scope=_scope(), deps=_Deps(7), message="q")
    assert isinstance(frames[-1], DoneFrame)


async def test_tool_calls_are_counted() -> None:
    async def lookup(ctx: RunContext[_Deps], key: str) -> str:
        """Look up a value for a key."""
        return f"val-{key}-{ctx.deps.subject_id}"

    agent, _ = _agent(TestModel(call_tools=["lookup"]), tools=[lookup])
    frames = await _drain(agent, scope=_scope(), deps=_Deps(9), message="q")
    done = frames[-1]
    assert isinstance(done, DoneFrame)
    assert done.tool_calls == 1


async def test_model_failure_becomes_error_frame_not_exception() -> None:
    agent, _ = _agent(_BoomModel())
    frames = await _drain(agent, scope=_scope(), deps=_Deps(7), message="q")
    assert len(frames) == 1
    assert isinstance(frames[0], ErrorFrame)
    assert "went wrong" in frames[0].message.lower()


async def test_failure_before_any_delta_records_no_usage() -> None:
    called = {"n": 0}

    def recorder(**kwargs):
        called["n"] += 1
        return 0.0

    agent = ToolChatAgent(
        model=_BoomModel(),
        model_name="m",
        instructions="p",
        deps_type=_Deps,
        recorder=recorder,
    )
    frames = [
        f async for f in agent.stream_turn(scope=_scope(), deps=_Deps(1), message="q")
    ]
    assert isinstance(frames[-1], ErrorFrame)
    assert called["n"] == 0  # no ledger write on a failed turn


def test_to_model_history_alternates_request_response() -> None:
    from pydantic_ai.messages import ModelRequest, ModelResponse

    history = to_model_history(
        [
            ChatMessage("user", "hi"),
            ChatMessage("assistant", "hello"),
            ChatMessage("user", "and now?"),
        ]
    )
    assert [type(m).__name__ for m in history] == [
        "ModelRequest",
        "ModelResponse",
        "ModelRequest",
    ]
    assert isinstance(history[0], ModelRequest)
    assert isinstance(history[1], ModelResponse)


async def test_history_is_passed_to_the_model() -> None:
    # A prior turn should be visible; TestModel echoes nothing useful, so we
    # assert the run simply succeeds with history present (conversion path).
    agent, _ = _agent(TestModel(custom_output_text="ok"))
    frames = await _drain(
        agent,
        scope=_scope(),
        deps=_Deps(7),
        message="follow up",
        history=[ChatMessage("user", "first"), ChatMessage("assistant", "reply")],
    )
    assert isinstance(frames[-1], DoneFrame)


class TestRecorderRunsOffTheEventLoop:
    """record_usage opens a SYNC db session - milliseconds, but on the
    streaming path's loop. The agent hands it to a worker thread."""

    async def test_recorder_called_in_a_thread(self) -> None:
        import threading

        seen: list[threading.Thread] = []

        def recorder(*, action, model_name, usage, user_id):
            seen.append(threading.current_thread())
            return 0.0

        agent = ToolChatAgent(
            model=TestModel(),
            model_name="claude-sonnet-5",
            instructions="You are a test persona.",
            deps_type=_Deps,
            action="chat:metrics",
            recorder=recorder,
        )
        await _drain(agent, scope=_scope(), deps=_Deps(7), message="hi")
        assert seen
        assert seen[0] is not threading.main_thread()
