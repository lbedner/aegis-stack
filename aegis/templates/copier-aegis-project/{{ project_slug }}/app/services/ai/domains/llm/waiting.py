"""Why a turn's answer has not started yet, when its engine can say.

The chat stream names a quiet stretch (``core.concurrency.announce_waiting``)
and asks this once per stretch. A local model may be loading, tens of
seconds of silence before its first token: "loading - 40s" is the same wait
as "waiting 40s" with the part that says it will finish. The turn's model
is the one its prompt was built for (``self_context``); its engine, through
the inference interface, says whether that model is in memory. A cloud
model, or a stack without the inference component, has no reason to give.

A prompt being read (prefill) is said as it moves: llama-server, asked
(``return_progress``), puts how far it is into the answer's own stream, and
``PrefillTee`` keeps the latest on the turn's ``Prefill`` as the bytes pass.
The stream reads it at every quiet tick, so nothing polls the server.
"""

from collections.abc import AsyncIterator
from contextvars import ContextVar
from dataclasses import dataclass
import json

import httpx

from app.core.discovery import present
from app.services.ai.domains.chat.self_context import TurnContext, current_turn
from app.services.ai.models.provider_names import LOCAL_PROVIDERS

INFERENCE = present("app.components.inference")
THINKING = "thinking"
# The turn whose model was found in memory: it stays so for the turn, so
# its engine is not asked again (each quiet stretch asked it, through every
# tool run and model round). A stream's stretches share one context.
_thinking: ContextVar[TurnContext | None] = ContextVar("thinking", default=None)


async def waiting_reason() -> str | None:
    """A short phrase for why nothing has arrived this turn, or None."""
    turn = current_turn()
    if not (INFERENCE and turn and turn.model and turn.provider in LOCAL_PROVIDERS):
        return None
    if _thinking.get() is turn:
        return THINKING
    from app.components.inference import get_inference_engine

    reason = await get_inference_engine(turn.provider).waiting_reason(turn.model)
    if reason == THINKING:
        _thinking.set(turn)
    return reason


@dataclass
class Prefill:
    """How far the server is through reading a prompt, as it last said
    (llama-server's ``prompt_progress``): ``processed`` counts the
    ``cache`` it reused, ``time_ms`` only the reading."""

    total: int = 0
    cache: int = 0
    processed: int = 0
    time_ms: int = 0

    def label(self) -> str | None:
        """The words while it reads; None before it says, or once read."""
        if not self.total or self.processed >= self.total:
            return None
        parts = [
            f"prefill {self.processed * 100 // self.total}%",
            f"{self.processed:,} / {self.total:,}",
        ]
        if self.time_ms:
            rate = (self.processed - self.cache) * 1000 // self.time_ms
            parts.append(f"{rate:,}/s")
        if self.cache:
            parts.append(f"{self.cache:,} cached")
        return " · ".join(parts)


# The turn's prefill, set by the stream that shows it (``watch_prefill``);
# the model's requests run in contexts copied from it, so they share it.
_prefill: ContextVar[Prefill | None] = ContextVar("prefill", default=None)
_MARK = b'"prompt_progress"'


def watch_prefill() -> Prefill:
    """Start keeping this turn's prefill, for the stream to read."""
    seen = Prefill()
    _prefill.set(seen)
    return seen


def current_prefill() -> Prefill | None:
    return _prefill.get()


class _Teed(httpx.AsyncByteStream):
    """A response body passed through as it came, its progress lines kept."""

    def __init__(self, inner: httpx.AsyncByteStream, seen: Prefill) -> None:
        self._inner = inner
        self._seen = seen

    async def __aiter__(self) -> AsyncIterator[bytes]:
        pending = b""
        async for chunk in self._inner:
            yield chunk
            *lines, pending = (pending + chunk).split(b"\n")
            for line in lines:
                if _MARK in line:
                    self._keep(line)

    def _keep(self, line: bytes) -> None:
        try:
            said = json.loads(line.removeprefix(b"data: "))["prompt_progress"]
            self._seen.total = int(said["total"])
            self._seen.cache = int(said["cache"])
            self._seen.processed = int(said["processed"])
            self._seen.time_ms = int(said["time_ms"])
        except (ValueError, KeyError, TypeError):
            return  # a line it cannot read says nothing; the answer goes on

    async def aclose(self) -> None:
        await self._inner.aclose()


class PrefillTee(httpx.AsyncBaseTransport):
    """The transport a llama-server model's client sends through: each
    response streams as it came, and while a turn watches, what it says of
    its reading lands on that turn's ``Prefill``."""

    def __init__(self, inner: httpx.AsyncBaseTransport | None = None) -> None:
        self._inner = inner or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        seen = _prefill.get()
        if seen is not None and isinstance(response.stream, httpx.AsyncByteStream):
            response.stream = _Teed(response.stream, seen)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()
