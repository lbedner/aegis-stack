"""ToolChatAgent — streaming tool-calling chat over pydantic-ai.

GENERIC. Wraps a pydantic-ai ``Agent`` with the chat kit's contracts: per-turn
context providers, a bounded tool loop, exact usage capture through the shared
ledger, and a frame-based streaming output. A caller supplies the model, a
frozen persona (``instructions``), tools, a deps type, and context providers;
the kit owns the turn mechanics.

Cache-aware turn shape: the persona is the constructor ``instructions``; the
per-turn context blocks are appended as RUN instructions (pydantic-ai appends
them after the constructor's), so the whole system block is persona + context
— stable bytes whenever the context is stable, which a provider cache
breakpoint serves at ~0.1x. Prior turns ride ``message_history`` (append-only,
caches incrementally); the current prompt is the user's plain message. Editing
the system prompt with *volatile* content every turn — what the template's
CLI chat does with health/usage snapshots — is what busts a cache; stable
context in the system block is what feeds one.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any, Generic, TypeVar

from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

from app.core.log import logger

from app.services.ai.usage_recording import extract_usage, record_usage
from .context import ContextProvider, compose_context, gather_context
from .models import (
    ChatMessage,
    ChatScope,
    DeltaFrame,
    DoneFrame,
    ErrorFrame,
    StreamFrame,
)


def to_model_history(messages: Sequence[ChatMessage]) -> list[ModelMessage]:
    """Convert stored ``(role, content)`` turns to pydantic-ai message history.

    User turns become ``ModelRequest``, assistant turns ``ModelResponse``.
    The kit stays model-agnostic in its stored form; this is the one place
    that speaks the provider's message shape.
    """
    history: list[ModelMessage] = []
    for msg in messages:
        if msg.role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=msg.content)]))
        else:
            history.append(ModelResponse(parts=[TextPart(content=msg.content)]))
    return history


# ``TypeVar`` + ``Generic`` rather than PEP 695 ``class Foo[DepsT]`` so the
# generated project imports on Python 3.11 (the template's floor).
DepsT = TypeVar("DepsT")


class ToolChatAgent(Generic[DepsT]):
    """A reusable streaming chat agent with context, tools, and cost control."""

    def __init__(
        self,
        *,
        model: Any,
        model_name: str,
        instructions: str,
        deps_type: type[DepsT],
        tools: Sequence[Any] = (),
        context_providers: Sequence[ContextProvider[DepsT]] = (),
        model_settings: ModelSettings | None = None,
        tool_calls_limit: int = 4,
        action: str = "chat:generic",
        recorder: Callable[..., float] = record_usage,
        capabilities: Sequence[Any] = (),
    ) -> None:
        """
        Args:
            model: A pydantic-ai model (string id or model instance). Tests
                inject ``TestModel`` / ``FunctionModel`` for a no-API seam.
            model_name: The ledger/pricing name for usage rows.
            instructions: The frozen persona prompt (stays cacheable).
            deps_type: The type of the caller's deps object (tools + providers
                receive it); the kit never inspects it.
            tools: pydantic-ai tools (plain callables or ``Tool`` instances).
            context_providers: Per-turn "what's true now" blocks.
            tool_calls_limit: Hard cap on tool calls per turn (bounds fan-out
                latency — the whole reason the design is briefing-first).
            action: Ledger action family for these turns (e.g. "chat:metrics").
            recorder: Usage-recording hook; injected in tests to assert cost.
            capabilities: pydantic-ai capabilities (e.g. code mode). Passed to
                the ``Agent`` only when non-empty, so stacks pinned to
                pre-capability pydantic-ai versions never see the kwarg.
        """
        agent_kwargs: dict[str, Any] = {}
        if capabilities:
            agent_kwargs["capabilities"] = list(capabilities)
        self._agent: Agent[DepsT] = Agent(
            model,
            instructions=instructions,
            deps_type=deps_type,
            tools=list(tools),
            model_settings=model_settings,
            **agent_kwargs,
        )
        self._model_name = model_name
        self._providers = tuple(context_providers)
        self._limits = UsageLimits(tool_calls_limit=tool_calls_limit)
        self._action = action
        self._recorder = recorder

    async def stream_turn(
        self,
        *,
        scope: ChatScope,
        deps: DepsT,
        message: str,
        history: Sequence[ChatMessage] = (),
    ) -> AsyncIterator[StreamFrame]:
        """Run one turn, yielding delta frames then a terminal done/error frame.

        The caller owns gating and persistence: gate + budget-check before
        calling this (emit ``BlockedFrame`` yourself), and persist the
        ``DoneFrame.answer`` + usage after it drains. The kit owns context
        assembly, the bounded tool loop, streaming, and usage recording.
        """
        blocks = await gather_context(self._providers, deps)
        run_instructions = compose_context(blocks)
        model_history = to_model_history(history)

        answer_parts: list[str] = []
        try:
            async with self._agent.run_stream(
                message,
                instructions=run_instructions,
                deps=deps,
                message_history=model_history,
                usage_limits=self._limits,
            ) as result:
                # debounce_by=None: pydantic-ai's default (0.1s) batches tokens
                # into 100ms clumps, which reads as stutter in the UI. Emit the
                # provider's chunks as they arrive; the client smooths display.
                async for delta in result.stream_text(delta=True, debounce_by=None):
                    answer_parts.append(delta)
                    yield DeltaFrame(delta)
                usage = extract_usage(result)
                tool_calls = _count_tool_calls(result)
        except Exception as exc:  # noqa: BLE001 - surface as a frame, never raise
            logger.warning(
                "chat turn failed",
                surface=scope.surface,
                user_id=scope.user_id,
                error=str(exc),
            )
            yield ErrorFrame("Something went wrong answering that. Please try again.")
            return

        answer = "".join(answer_parts)
        # The default recorder opens a SYNC db session (usage_recording):
        # milliseconds of blocking, but on the streaming loop - a worker
        # thread keeps the turn's tail latency off every other session.
        cost = await asyncio.to_thread(
            self._recorder,
            action=self._action,
            model_name=self._model_name,
            usage=usage,
            user_id=scope.user_id,
        )
        yield DoneFrame(
            answer=answer, usage=usage, cost_usd=cost, tool_calls=tool_calls
        )


def _count_tool_calls(result: Any) -> int:
    """Best-effort count of tool calls made this turn, for observability.

    Reads the run's messages for tool-call parts; degrades to 0 rather than
    raising, since it only feeds a telemetry field on the done frame.
    """
    try:
        messages = result.all_messages()
    except Exception:
        return 0
    count = 0
    for message in messages:
        for part in getattr(message, "parts", ()):
            if type(part).__name__ == "ToolCallPart":
                count += 1
    return count
