"""What a coding agent's command printed, read: its session's lines as
they come (``heard``, Claude Code's stream-json) and its own answer at the
end (``read``), with what the session cost."""

import json
import math
from typing import Any

from .protocol import CALLED, MOST_LINE, RETURNED, SAID, Answer, Line


def heard(printed: str) -> list[Line]:
    """What one line of an agent's session (Claude Code's stream-json) says:
    what it said, each tool it called with what it was given, and what a
    tool gave back, each cut to ``MOST_LINE``; nothing for its own events,
    its thinking, or a line that is not one."""
    try:
        event = json.loads(printed)
    except ValueError:
        return []
    if not isinstance(event, dict) or event.get("type") not in ("assistant", "user"):
        return []
    blocks = (event.get("message") or {}).get("content")
    found: list[tuple[str, str]] = []
    for block in blocks if isinstance(blocks, list) else []:
        kind = block.get("type") if isinstance(block, dict) else None
        if kind == "text" and event["type"] == "assistant" and block.get("text"):
            found.append((SAID, block["text"]))
        elif kind == "tool_use":
            given = json.dumps(block.get("input"), ensure_ascii=False)
            found.append((CALLED, f"{block.get('name')} {given}"))
        elif kind == "tool_result":
            found.append((RETURNED, _text_of(block.get("content"))))
    return [Line(kind=kind, text=text[:MOST_LINE]) for kind, text in found]  # type: ignore[arg-type]


def _text_of(content: Any) -> str:
    """A tool's result as text: itself, or its text parts, a line each."""
    if isinstance(content, str):
        return content
    parts = content if isinstance(content, list) else []
    return "\n".join(p["text"] for p in parts if isinstance(p, dict) and "text" in p)


def read(printed: str) -> Answer | None:
    """A coding agent's own answer in what a command printed (one JSON
    object, last if anything came before it, that is a ``result`` or says
    its ``total_cost_usd``): what it said, or failing why (its ``errors``,
    else the kind of failure), whether it ``is_error``, and what its
    session has cost (where that is an amount). None for anything else:
    plain output."""
    text = printed.strip()
    for candidate in (text, *reversed(text.splitlines())):
        try:
            said = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(said, dict) and (
            said.get("type") == "result" or "total_cost_usd" in said
        ):
            break
    else:
        return None
    cost = said.get("total_cost_usd")
    why = "\n".join(map(str, said.get("errors") or [])) or said.get("subtype")
    numbered = (
        isinstance(cost, int | float)
        and not isinstance(cost, bool)
        and math.isfinite(cost)
        and cost >= 0
    )
    return Answer(
        ok=not said.get("is_error"),
        result=str(said.get("result") or why or ""),
        cost=cost if numbered else None,
    )
