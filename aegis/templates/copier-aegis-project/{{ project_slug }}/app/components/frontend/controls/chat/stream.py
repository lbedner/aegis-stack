"""Pure streaming-text logic for the chat panel.

Everything here is UI-framework-free so it can be tested directly: the
accumulator that turns SSE chunk payloads into render-safe markdown
snapshots, and the fence balancer that keeps partial output from
breaking the markdown control mid-stream.
"""

import ast
from dataclasses import dataclass, field
import json
import pprint
from typing import Any

# Rendered while text is still arriving; dropped from the final render.
STREAM_CURSOR = "▌"


def balance_fences(text: str) -> str:
    """Close an unterminated code fence so partial markdown renders sanely.

    A streaming response frequently pauses inside a ``` block; rendering
    that verbatim makes the markdown control swallow everything after the
    opening fence. An odd fence count gets a synthetic closer appended.
    """
    if text.count("```") % 2 == 1:
        return f"{text}\n```"
    return text


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


def tool_label(name: str, args: str = "") -> str:
    """One trail line for a tool call: ``ledger(months=3)``.

    A code-mode script call arrives as ``{"code": "<first line>"}`` and
    reads as ``run_code: <first line>`` - what the script was FOR, not
    a parenthesized argument dump.
    """
    if not name:
        return "working..."
    inner = ""
    if args:
        try:
            parsed = json.loads(args)
        except (ValueError, TypeError):
            inner = args
        else:
            if isinstance(parsed, dict) and set(parsed) == {"code"}:
                return f"{name}: {parsed['code']}"
            if isinstance(parsed, dict):
                inner = ", ".join(f"{key}={value}" for key, value in parsed.items())
            elif parsed is not None:
                inner = str(parsed)
    return f"{name}({inner})"


def trace_label(entry: dict[str, Any]) -> str:
    """A persisted trace entry as its trail line (same look as live)."""
    name = str(entry.get("tool", ""))
    code = entry.get("code")
    if isinstance(code, str):
        for line in code.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return f"{name}: {stripped[:80]}"
        return f"{name}:"
    return tool_label(name, str(entry.get("args", "") or ""))


def _pretty(text: str) -> str:
    """Printed output made readable: each line that parses as a Python
    or JSON literal is re-rendered through pprint (wrapped to the trace
    dialog's width); everything else passes through untouched."""
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("{", "[", "(")):
            lines.append(line)
            continue
        try:
            value = ast.literal_eval(stripped)
        except (ValueError, SyntaxError):
            try:
                value = json.loads(stripped)
            except ValueError:
                lines.append(line)
                continue
        lines.append(pprint.pformat(value, width=72, sort_dicts=False))
    return "\n".join(lines)


def trace_output(entry: dict[str, Any]) -> str:
    """The human part of a trace entry's result: the printed output when
    the result parses as a run_code return, the raw text otherwise."""
    result = entry.get("result")
    if not isinstance(result, str) or not result:
        return ""
    try:
        parsed = json.loads(result)
    except ValueError:
        return result
    if isinstance(parsed, dict):
        # run_code results arrive as {"return_value": {"output": ...}}
        # or the flat {"output": ...}; either way show the printed text.
        value = parsed.get("return_value", parsed)
        if isinstance(value, dict) and isinstance(value.get("output"), str):
            return _pretty(value["output"])
        if isinstance(value, dict) or isinstance(value, list):
            return pprint.pformat(value, width=72, sort_dicts=False)
        if value is not None:
            return str(value)
    return _pretty(result)


_FAILURE_MARKS = ("Type error in code", "Runtime error", "Fix the errors")


def trace_failed(entry: dict[str, Any]) -> bool:
    """Whether a trace entry's result is a sandbox failure report - the
    trail marks these so a spiral of failing scripts is visible instead
    of reading like quiet success."""
    result = entry.get("result")
    return isinstance(result, str) and any(m in result for m in _FAILURE_MARKS)


def narration_note(text: str, limit: int = 100) -> str:
    """Pre-tool narration folded into the trail instead of vanishing:
    one clipped line ("" when there was nothing to keep)."""
    flat = " ".join(text.split())
    if not flat:
        return ""
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


def footer_line(meta: dict[str, Any]) -> str:
    """One quiet attribution line for a finished assistant message."""
    parts: list[str] = []
    if meta.get("model"):
        parts.append(str(meta["model"]))
    if meta.get("gen_tps"):
        parts.append(f"{meta['gen_tps']} tps")
    cost = meta.get("cost")
    if cost:
        parts.append(f"${cost:.4f}")
    return "  ·  ".join(parts)
