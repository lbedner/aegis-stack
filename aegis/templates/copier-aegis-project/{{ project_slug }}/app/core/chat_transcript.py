"""The words a chat transcript shows around the model's text.

Pure functions, shared by every surface that renders a conversation (the
web chat page, the Flet panel): the fence balancer that keeps partial
markdown from swallowing what follows an open code block, the trail
labels for tool calls, the attachment gate and marker, and the footer
line under a finished answer.
"""

from __future__ import annotations

import ast
import json
import pprint
import re
from typing import Any

# Rendered while text is still arriving; dropped from the final render.
STREAM_CURSOR = "▌"

# The image types a chat attachment may carry, by upload extension.
_IMAGE_MEDIA_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}


def image_media_type(filename: str) -> str | None:
    """Mime type for an image attachment by extension, None otherwise.

    The gate for the attach picker: anything returning None is refused
    client-side instead of failing in the model call."""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _IMAGE_MEDIA_TYPES.get(extension)


# The service's stored-history marker for image parts - the format
# written by ``services/ai/domains/chat/attachments.annotate_attachments``.
_ATTACHMENT_MARKER = re.compile(r"\n\n\[attached \d+ images?: [^\]\n]*\]$")


def strip_attachment_marker(text: str) -> str:
    """A replayed message must not carry its old attachment marker: the
    bytes are gone (they ride one turn only), so re-sending the marker
    would claim images the model cannot see."""
    return _ATTACHMENT_MARKER.sub("", text)


def balance_fences(text: str) -> str:
    """Close an unterminated code fence so partial markdown renders sanely.

    A streaming response frequently pauses inside a ``` block; rendering
    that verbatim makes the markdown control swallow everything after the
    opening fence. An odd fence count gets a synthetic closer appended.
    """
    if text.count("```") % 2 == 1:
        return f"{text}\n```"
    return text


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
