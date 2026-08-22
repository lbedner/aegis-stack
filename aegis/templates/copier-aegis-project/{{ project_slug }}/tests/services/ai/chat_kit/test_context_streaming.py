"""Context gathering + NDJSON streaming serialization."""

from __future__ import annotations

from dataclasses import dataclass
import json

from app.services.ai.domains.chat.chat_kit import (
    DeltaFrame,
    DoneFrame,
    StaticContextProvider,
    compose_context,
    gather_context,
    ndjson_line,
    ndjson_response,
)
from app.services.ai.domains.chat.chat_kit.models import BlockedFrame, ErrorFrame


@dataclass
class _Deps:
    subject_id: int


async def test_gather_context_collects_nonempty_blocks() -> None:
    providers = (
        StaticContextProvider("a", "block-a"),
        StaticContextProvider("empty", ""),  # None-equivalent, dropped
        StaticContextProvider("b", "block-b"),
    )
    blocks = await gather_context(providers, _Deps(1))
    assert blocks == [("a", "block-a"), ("b", "block-b")]


async def test_gather_context_isolates_a_failing_provider() -> None:
    class _Boom:
        name = "boom"

        async def build(self, deps) -> str | None:
            raise RuntimeError("provider blew up")

    providers = (
        StaticContextProvider("ok", "kept"),
        _Boom(),
        StaticContextProvider("ok2", "also-kept"),
    )
    # The failure is swallowed with a warning; the turn keeps its other context.
    blocks = await gather_context(providers, _Deps(1))
    assert blocks == [("ok", "kept"), ("ok2", "also-kept")]


def test_compose_context_without_blocks_is_none() -> None:
    assert compose_context([]) is None


def test_ndjson_line_is_one_compact_json_line() -> None:
    line = ndjson_line(DeltaFrame("hi"))
    assert line.endswith("\n")
    assert line.count("\n") == 1
    assert json.loads(line) == {"kind": "delta", "text": "hi"}


def test_frame_serialization_shapes() -> None:
    assert json.loads(ndjson_line(DoneFrame("ans", {"input_tokens": 3}, 0.01, 2))) == {
        "kind": "done",
        "answer": "ans",
        "usage": {"input_tokens": 3},
        "cost_usd": 0.01,
        "tool_calls": 2,
    }
    assert json.loads(ndjson_line(BlockedFrame("budget", "Daily limit reached."))) == {
        "kind": "blocked",
        "reason": "budget",
        "message": "Daily limit reached.",
    }
    assert json.loads(ndjson_line(ErrorFrame("nope"))) == {
        "kind": "error",
        "message": "nope",
    }


async def test_ndjson_response_headers_and_body() -> None:
    async def frames():
        yield DeltaFrame("part-1")
        yield DoneFrame("part-1", {"input_tokens": 1, "output_tokens": 1}, 0.0)

    response = ndjson_response(frames())
    assert response.media_type == "application/x-ndjson"
    assert response.headers["X-Accel-Buffering"] == "no"
    assert response.headers["Cache-Control"] == "no-cache"

    # body_iterator yields the raw NDJSON strings; ASGI encodes them on send.
    body = "".join([chunk async for chunk in response.body_iterator])
    lines = body.strip().split("\n")
    assert json.loads(lines[0])["kind"] == "delta"
    assert json.loads(lines[1])["kind"] == "done"
