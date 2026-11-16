"""Why a turn's answer has not started, said while the stream is quiet.

Every chat stream (``sse.turn_stream``) sends a ``waiting`` frame while
nothing is arriving: how long, and why when the turn's model runs on this
machine (its engine says whether the model is loaded). A cloud model, or a
stack without the inference component, waits on a plain stopwatch.
"""

import asyncio
from collections.abc import AsyncIterator
import contextvars
from datetime import UTC, datetime
import functools
import json

import pytest

from app.components.backend.api.ai import sse
from app.core.discovery import present
from app.services.ai.domains.chat.self_context import (
    begin_turn_context,
    record_turn_context,
)
from app.services.ai.domains.llm import waiting
from app.services.ai.service import StreamingMessage

INFERENCE = present("app.components.inference")


def _turn(provider: str, model: str) -> None:
    begin_turn_context()
    record_turn_context(provider=provider, model=model)


class TestTheReason:
    async def test_before_the_prompt_is_built_there_is_none(self) -> None:
        """Nothing has gone to a model yet: there is nothing to explain."""
        fresh = contextvars.Context()
        reason = asyncio.create_task(waiting.waiting_reason(), context=fresh)
        assert await reason is None

    async def test_a_cloud_model_has_none(self) -> None:
        _turn("openai", "gpt-4o")
        assert await waiting.waiting_reason() is None

    @pytest.mark.skipif(not INFERENCE, reason="no inference component")
    async def test_a_local_model_asks_its_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.components.inference as inference

        asked: list[tuple[str, str]] = []

        class Engine:
            def __init__(self, name: str) -> None:
                self.name = name

            async def waiting_reason(self, model: str) -> str:
                asked.append((self.name, model))
                return "loading"

        monkeypatch.setattr(inference, "get_inference_engine", Engine)
        _turn("llamacpp", "qwen")

        assert await waiting.waiting_reason() == "loading"
        assert asked == [("llamacpp", "qwen")]

    @pytest.mark.skipif(not INFERENCE, reason="no inference component")
    @pytest.mark.parametrize(("said", "asks"), [("thinking", 1), ("loading", 2)])
    async def test_a_model_found_thinking_is_not_asked_after(
        self, monkeypatch: pytest.MonkeyPatch, said: str, asks: int
    ) -> None:
        """Asked every quiet stretch, the engine was read every two seconds
        of every tool run and model round. A model in memory stays so for
        the turn; one loading is asked again until it is in."""
        import app.components.inference as inference

        asked: list[str] = []

        class Engine:
            def __init__(self, name: str) -> None:
                pass

            async def waiting_reason(self, model: str) -> str:
                asked.append(model)
                return said

        monkeypatch.setattr(inference, "get_inference_engine", Engine)
        _turn("ollama", "qwen")

        assert [await waiting.waiting_reason() for _ in range(2)] == [said, said]
        assert len(asked) == asks

    async def test_without_the_inference_component_there_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(waiting, "INFERENCE", False)
        _turn("ollama", "qwen")
        assert await waiting.waiting_reason() is None


def _frames(body: list[str]) -> list[tuple[str, dict[str, object]]]:
    pairs = []
    for frame in body:
        head, data = frame.strip().split("\n")
        pairs.append((head.removeprefix("event: "), json.loads(data[6:])))
    return pairs


def _quick(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stream that counts as quiet after 0.05s."""
    monkeypatch.setattr(
        sse, "announce_waiting", functools.partial(sse.announce_waiting, every=0.05)
    )


def _message(**metadata: object) -> StreamingMessage:
    return StreamingMessage(
        content="hi",
        is_final=False,
        is_delta=True,
        message_id="m",
        conversation_id="c",
        timestamp=datetime.now(UTC),
        metadata=metadata,
    )


async def test_a_running_tool_is_not_the_model_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quiet while a tool runs: the model is not thinking, so its engine
    is not asked, and the wait has no reason."""
    asked: list[bool] = []

    async def explain() -> str:
        asked.append(True)
        return "thinking"

    async def tool_then_text() -> AsyncIterator[StreamingMessage]:
        yield _message(event="tool", tool="run_code")
        await asyncio.sleep(0.2)
        yield _message()

    _quick(monkeypatch)
    monkeypatch.setattr(sse, "waiting_reason", explain)
    frames = _frames([f async for f in sse._events(tool_then_text())])

    waits = [data for name, data in frames if name == "waiting"]
    assert waits and all(wait["reason"] is None for wait in waits)
    assert asked == []


async def test_a_quiet_stream_sends_how_long_and_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def explain() -> str:
        return "loading"

    async def slow() -> AsyncIterator[StreamingMessage]:
        await asyncio.sleep(0.2)
        yield StreamingMessage(
            content="hi",
            is_final=False,
            is_delta=True,
            message_id="m",
            conversation_id="c",
            timestamp=datetime.now(UTC),
        )

    _quick(monkeypatch)
    monkeypatch.setattr(sse, "waiting_reason", explain)
    frames = _frames([f async for f in sse._events(slow())])

    names = [name for name, _ in frames]
    assert names[0] == "connect" and "chunk" in names
    waits = [data for name, data in frames if name == "waiting"]
    assert waits and names.index("waiting") < names.index("chunk")
    # The words the bubble shows are the server's.
    assert waits[0] == {"seconds": 0, "reason": "loading", "label": "loading - 0s"}
