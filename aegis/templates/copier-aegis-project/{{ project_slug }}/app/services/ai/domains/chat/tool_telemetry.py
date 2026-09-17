"""Per-tool-call ledger for chat agents.

``llm_usage`` records a turn: model, tokens, cost, duration. It cannot say
which tool ran inside it. That gap matters as soon as an agent has more than
a couple of tools, because the questions you want to ask are about the tools
and not the turn: which ones are never reached for, which are always called
together, and how often a turn spends its whole call budget and still answers
short.

Instrumentation hangs off ``resolve_tools`` - the single seam every agent's
callables pass through - so a new tool is measured by existing, and no tool
module has to remember a decorator.

Two things are deliberate:

* **Turn identity is a context variable**, set once around the model call the
  same way ``memory_user`` binds the turn's owner. The kit is generic over a
  deps type it never inspects, so there is nowhere on deps to put it.
* **Ceiling hits are derived, not flagged.** Each row carries its index within
  the turn, so "this turn used its whole budget" is ``max(call_index) + 1 ==
  the agent's tool-call limit`` at query time. Nothing has to know the limit
  at write time.

Recording never fails a turn. A ledger that can break the feature it measures
is worse than no ledger.
"""

from __future__ import annotations

import functools
import inspect
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core.log import logger

# Errors are stored for triage, not for display; a stack-sized string in a
# telemetry row helps nobody.
MAX_ERROR_CHARS = 500


@dataclass
class TurnTelemetry:
    """Identity and call counter for one turn."""

    turn_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    user_id: str | None = None
    agent_slug: str | None = None
    conversation_id: str | None = None
    calls: int = 0

    def next_index(self) -> int:
        index = self.calls
        self.calls += 1
        return index


current_turn: ContextVar[TurnTelemetry | None] = ContextVar(
    "current_tool_turn", default=None
)


@contextmanager
def tool_turn(
    *,
    user_id: str | None = None,
    agent_slug: str | None = None,
    conversation_id: str | None = None,
) -> Iterator[TurnTelemetry]:
    """Bind a turn so the tools it calls land in one group.

    Without it a tool call still records, under its own one-off turn id:
    losing the grouping is better than losing the call.
    """
    turn = TurnTelemetry(
        user_id=user_id, agent_slug=agent_slug, conversation_id=conversation_id
    )
    token = current_turn.set(turn)
    try:
        yield turn
    finally:
        current_turn.reset(token)


async def _write(
    *,
    turn: TurnTelemetry,
    tool_name: str,
    call_index: int,
    duration_ms: int,
    result_bytes: int,
    ok: bool,
    error: str | None,
) -> None:
    """Insert one row on its own session.

    Its own session, not whatever the tool was handed: the tool's session
    usually belongs to the request transaction, which is still open. A
    telemetry insert has no business being rolled back with it, or holding
    it open while the model thinks.
    """
    try:
        from app.core.db import AsyncSessionLocal
        from app.services.ai.models.agents import AgentToolCall
    except ImportError:
        # A memory-backend project has no agent tables at all (post-gen
        # removes them). The wrapper stays in the call path so the code is
        # one shape everywhere; there is simply nowhere to write, and a
        # warning per tool call would be worse than silence.
        return

    try:
        async with AsyncSessionLocal() as session:
            session.add(
                AgentToolCall(
                    turn_id=turn.turn_id,
                    tool_name=tool_name,
                    call_index=call_index,
                    duration_ms=duration_ms,
                    result_bytes=result_bytes,
                    ok=ok,
                    error=None if error is None else error[:MAX_ERROR_CHARS],
                    user_id=turn.user_id,
                    agent_slug=turn.agent_slug,
                    conversation_id=turn.conversation_id,
                    created_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001 - telemetry must not break a turn
        logger.warning("tool-call ledger write failed", tool=tool_name, error=str(exc))


def _size_of(result: Any) -> int:
    """How much context the result cost, best effort."""
    if isinstance(result, str):
        return len(result.encode())
    try:
        return len(str(result).encode())
    except Exception:  # noqa: BLE001 - a weird repr is not worth a failed turn
        return 0


def instrument(name: str, func: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a tool callable so its call lands in the ledger.

    ``functools.wraps`` is load-bearing rather than tidy: the agent framework
    builds the tool schema the model sees from the callable's name, signature
    and docstring, so a lossy wrapper would silently change the tool.

    Sync tools are wrapped too - the sandbox and some registries hold plain
    functions - but their row is written on a best-effort background task,
    since a sync tool has no place to await from.
    """

    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            turn = current_turn.get() or TurnTelemetry()
            index = turn.next_index()
            started = time.perf_counter()
            error: str | None = None
            result: Any = None
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                await _write(
                    turn=turn,
                    tool_name=name,
                    call_index=index,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    result_bytes=_size_of(result),
                    ok=error is None,
                    error=error,
                )

        return async_wrapper

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        import asyncio

        turn = current_turn.get() or TurnTelemetry()
        index = turn.next_index()
        started = time.perf_counter()
        error: str | None = None
        result: Any = None
        try:
            result = func(*args, **kwargs)
            return result
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            payload = {
                "turn": turn,
                "tool_name": name,
                "call_index": index,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "result_bytes": _size_of(result),
                "ok": error is None,
                "error": error,
            }
            try:
                # A sync tool called from the event loop cannot await; hand
                # the insert to the loop. Outside a loop entirely (a CLI, a
                # test), drop it rather than spin one up for telemetry.
                asyncio.get_running_loop().create_task(_write(**payload))  # type: ignore[arg-type]
            except RuntimeError:
                logger.debug("tool-call ledger skipped, no event loop", tool=name)

    return sync_wrapper
