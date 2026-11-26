"""A live call's turn: gathered from the session's events (``TurnLog``,
how long the caller waited for its first word included), and once finished
kept in its conversation as a typed turn is kept (``realtime_calls.drive``
saves each one); and the tool a call ends on (``end_call``)."""

from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any

from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartEndEvent,
    RealtimeInputSpeechEndEvent,
    RealtimeInputSpeechStartEvent,
    RealtimeTurnCompleteEvent,
    SpeechPart,
    SpeechPartDelta,
)

from app.services.ai.domains.chat.cards import attach_cards
from app.services.ai.models import MessageRole
from app.services.ai.service.trace import record_tool_call, record_tool_result


def end_call() -> str:
    """End the call. Use it once they have said they are done - a goodbye,
    "that's all", thanks with nothing more to ask - right after your short
    goodbye, and say nothing after it. Never on a turn with no words of
    theirs in it (a noise, a breath, your own voice heard back): that is
    not a goodbye, so carry on or ask what they meant."""
    return "The call ends when your goodbye has played. Say nothing more."


# The tool a call ends on (``realtime_calls.CALL_TOOLS``).
END_CALL = end_call.__name__


class TurnLog:
    """One turn, gathered from the session's events: what was heard, what
    was said, and the steps, recorded as a streamed turn records them."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._reset()
        self._clock = clock
        # When the caller last stopped speaking, until the reply's first
        # audio; then how long that took (``first_word_ms``), for the turn
        # to keep. A provider that never says the caller stopped (Gemini
        # Live) is not timed.
        self._quiet_at: float | None = None
        self.first_word_ms: int | None = None
        # From then to the reply's end, every step between: how long the
        # turn took (``response_time_ms``, as a typed turn keeps it).
        self._asked_at: float | None = None
        self.response_time_ms: int | None = None
        # The cards the call's steps draw (its card stage), moved onto the
        # step that drew them; the call's, not a turn's.
        self.drawn: list[dict[str, Any]] = []
        # The cards the last event's step drew, for the page at once.
        self.shown: list[str] = []

    def _reset(self) -> None:
        self.heard: list[str] = []
        self.said: list[str] = []
        self.trace: list[dict[str, Any]] = []

    def observe(self, event: Any) -> bool:
        """Take in one event; True when it finished a turn. Ending the call
        is how it ends, not one of the steps."""
        self.shown = []
        if (
            isinstance(event, FunctionToolCallEvent | FunctionToolResultEvent)
            and event.part.tool_name == END_CALL
        ):
            return False
        if isinstance(event, RealtimeInputSpeechStartEvent):
            self._quiet_at = self._asked_at = None
        elif isinstance(event, RealtimeInputSpeechEndEvent):
            self._quiet_at = self._asked_at = self._clock()
        elif (
            isinstance(event, PartDeltaEvent)
            and isinstance(event.delta, SpeechPartDelta)
            and event.delta.audio_chunk
            and self._quiet_at is not None
        ):
            self.first_word_ms = round((self._clock() - self._quiet_at) * 1000)
            self._quiet_at = None
        elif isinstance(event, PartEndEvent) and isinstance(event.part, SpeechPart):
            text = (event.part.transcript or "").strip()
            side = self.heard if event.part.speaker == "user" else self.said
            # The same part reported finished twice is not more speech.
            if text and (not side or side[-1] != text):
                side.append(text)
        elif isinstance(event, FunctionToolCallEvent):
            record_tool_call(self.trace, event)
        elif isinstance(event, FunctionToolResultEvent):
            finished = record_tool_result(self.trace, event)
            self.shown = [marker["id"] for marker in self.drawn]
            attach_cards(finished, self.drawn)
        elif isinstance(event, RealtimeTurnCompleteEvent):
            if self._asked_at is not None:
                self.response_time_ms = round((self._clock() - self._asked_at) * 1000)
                self._asked_at = None
            return True
        return False

    def take(self) -> tuple[str, str, list[dict[str, Any]]] | None:
        """The finished turn, once; None when nothing was said."""
        heard, said, trace = " ".join(self.heard), " ".join(self.said), self.trace
        self._reset()
        if not heard and not said:
            return None
        return heard, said, trace


async def save_turn(
    ai: Any,
    conversation_id: str,
    heard: str,
    said: str,
    trace: list[dict[str, Any]],
    *,
    model: str,
    provider: str,
    usage: dict[str, Any] | None = None,
    interrupted: bool = False,
) -> None:
    """The turn into the conversation, as a typed turn is kept: ``usage``
    is its share of the call (tokens and cost), for its footer. A turn the
    call dropped in the middle of is ``interrupted``, and keeps what was
    asked so the next call can pick it up (``resumed``)."""
    conversation = await ai.get_conversation(conversation_id)
    if conversation is None:
        return
    if heard:
        conversation.add_message(MessageRole.USER, heard)
    metadata: dict[str, Any] = {
        "conversation_id": conversation_id,
        "provider": provider,
        "model": model,
        "stream_complete": True,
    }
    if trace:
        metadata["tool_trace"] = trace
    metadata.update(usage or {})
    if interrupted:
        metadata.update(interrupted=True, asked=heard)
    conversation.add_message(MessageRole.ASSISTANT, said, metadata=metadata)
    await ai.conversation_manager.save_conversation(conversation)
