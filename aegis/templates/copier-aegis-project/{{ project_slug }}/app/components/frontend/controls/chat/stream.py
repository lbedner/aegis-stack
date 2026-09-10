"""Pure streaming-text logic for the chat panel.

The accumulator that turns SSE chunk payloads into render-safe markdown
snapshots. The transcript words themselves (fence balancing, trail
labels, the footer) live in ``app/core/chat_transcript.py``
and are re-exported here for the panel and its tests.
"""

from dataclasses import dataclass, field
from typing import Any

from app.core.chat_transcript import (  # noqa: F401  (re-export)
    STREAM_CURSOR,
    balance_fences,
    footer_line,
    image_media_type,
    narration_note,
    strip_attachment_marker,
    tool_label,
    trace_failed,
    trace_label,
    trace_output,
)


@dataclass
class StreamAccumulator:
    """Collects delta chunks and exposes render-safe snapshots.

    The panel appends every ``chunk`` payload's content here and renders
    ``snapshot()`` on a throttle; ``finalize()`` returns the exact final
    text plus the metadata the ``final`` event carried (model, cost,
    tokens-per-second) for the message footer.
    """

    parts: list[str] = field(default_factory=list)
    final_meta: dict[str, Any] = field(default_factory=dict)
    conversation_id: str | None = None

    def add_chunk(self, payload: dict[str, Any]) -> None:
        content = payload.get("content") or ""
        if content:
            self.parts.append(content)
        if payload.get("conversation_id"):
            self.conversation_id = payload["conversation_id"]

    tool_trace: list[dict[str, Any]] = field(default_factory=list)

    def reset_text(self) -> None:
        """Drop text streamed so far (pre-tool-call running commentary);
        the answer is whatever follows the last tool call."""
        self.parts.clear()

    def add_final(self, payload: dict[str, Any]) -> None:
        # The final event repeats the full content; keep the streamed
        # parts authoritative unless nothing streamed (non-delta mode).
        if not self.parts and payload.get("content"):
            self.parts.append(payload["content"])
        if payload.get("tool_trace"):
            self.tool_trace = payload["tool_trace"]
        if payload.get("conversation_id"):
            self.conversation_id = payload["conversation_id"]
        self.final_meta = {
            key: payload[key]
            for key in ("model", "provider", "cost", "gen_tps", "response_time_ms")
            if payload.get(key) is not None
        }

    @property
    def text(self) -> str:
        return "".join(self.parts)

    def snapshot(self) -> str:
        """The in-flight render: fence-balanced, with a typing cursor."""
        return balance_fences(f"{self.text}{STREAM_CURSOR}")

    def final_text(self) -> str:
        return self.text
