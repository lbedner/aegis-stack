"""The words a chat transcript shows around the model's text.

Pure functions, shared by every surface that renders a conversation (the
web chat page, the Flet panel): the fence balancer that keeps partial
markdown from swallowing what follows an open code block, the trail
labels for tool calls, the attachment gate and marker, a paste's marker,
and the footer line under a finished answer.
"""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Iterable
import json
import pprint
import re
from typing import Any

from app.core.config import settings
from app.core.formatting import counted
from app.core.steps import doing
from app.core.tools import card_tool_names, result_data

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
# Every image a turn may carry: what a model is shown. The one list: a
# chat turn's attachments, a pasted image and a document read as a picture
# all take these.
IMAGE_TYPES = frozenset(_IMAGE_MEDIA_TYPES.values())
# The most one attached or pasted file may weigh.
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


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


# What stands in a message for a paste kept apart from it
# (``services/ai/domains/chat/pastes``): written by ``paste_marker``, read
# back by ``paste_ids``, taken out of what a reader sees by ``readable``.
# The id is the whole hex run: what follows it starts with a non-hex
# character, so the two never contend for one (an unclosed marker over a
# long run of digits backtracked quadratically). The tail stops at either
# bracket - a name's are swapped out (``paste_marker``) - so a message of
# unclosed markers is not rescanned from each one's start.
_PASTE_MARKER = re.compile(r"\[pasted text #([0-9a-f]+)(?:[^\]\[0-9a-f][^\]\[]*)?\]")


def paste_marker(paste_id: str, title: str, chars: int) -> str:
    """The line the model gets where a paste was: what it is and how to
    read it, since a marker the agent cannot act on is a hole in the
    conversation. A bracket in the name would end the marker early."""
    name = title.replace("[", "(").replace("]", ")")
    return (
        f"[pasted text #{paste_id}: {name} - {paste_size(chars)}."
        f' Read it with pasted("{paste_id}")]'
    )


def paste_size(chars: int) -> str:
    """How big a paste is, as its marker and its chip say it."""
    return counted(chars, "character")


def paste_ids(text: str) -> list[str]:
    """The pastes a message's markers name, in order."""
    return _PASTE_MARKER.findall(text)


def readable(content: str) -> str:
    """A stored message as its reader gets it, on screen or aloud: no
    attachment note, and no paste marker (the paste is a chip beside it)."""
    return _PASTE_MARKER.sub("", strip_attachment_marker(content)).strip()


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


def shows_calls() -> bool:
    """Whether a step's trail line is its call or what it is doing
    (``AI_CHAT_SHOW_CALLS``). Read with a default: this module ships in
    stacks without AI, whose settings have no such field."""
    return bool(getattr(settings, "AI_CHAT_SHOW_CALLS", True))


def script_of(args: Any) -> str | None:
    """A code-mode call's script, from its arguments as a JSON string or
    already parsed; None for any other call."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return None
    code = args.get("code") if isinstance(args, dict) else None
    return code if isinstance(code, str) else None


def first_code_line(code: str) -> str:
    """A script's first line of code (no blank, no comment), clipped:
    what the script was FOR, not the program."""
    for line in code.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:80]
    return ""


def trail_label(name: str, args: Any) -> str:
    """A call's trail line, live and stored alike: the call, or what it is
    doing (``steps.doing``, read from the whole script while its first
    comment is still there) where ``AI_CHAT_SHOW_CALLS`` is off, so a
    viewer sees the agent's steps, not its code."""
    script = script_of(args)
    text = args if isinstance(args, str) else json.dumps(args, default=str)
    if not shows_calls():
        return doing(name, text if script is None else script)
    if script is None:
        return tool_label(name, text)
    return f"{name}: {first_code_line(script)}".rstrip()


def trace_label(entry: dict[str, Any]) -> str:
    """A persisted trace entry as its trail line (same look as live)."""
    code = entry.get("code")
    args = {"code": code} if isinstance(code, str) else str(entry.get("args", "") or "")
    return trail_label(str(entry.get("tool", "")), args)


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


# What an approval card's status (``card_outcome``) reads as, and its tone,
# in every chat UI (the Flet chat and the htmx one); each UI maps a tone to
# its colours.
CARD_STATUS: dict[str, tuple[str, str]] = {
    "pending": ("Awaiting your approval", "warn"),
    "approved": ("Approved", "ok"),
    "rejected": ("Rejected", "error"),
    "withdrawn": ("Withdrawn", "muted"),
    "expired": ("Expired", "muted"),
}


# How a withdrawal's note starts (``change_queue.withdraw`` writes it).
WITHDRAWN = "Withdrawn"


def proposer_line(proposed_by_agent: str | None) -> str | None:
    """Who filed a card, as every card UI shows it: a card from an
    outside assistant (``mcp:<client>``) must never read as the app's own
    assistant's."""
    return f"Proposed by {proposed_by_agent}" if proposed_by_agent else None


def card_outcome(status: str, note: Any) -> str:
    """A card's status as a person reads it: a rejection the proposing
    agent filed against itself is "withdrawn", not the user saying no."""
    if status == "rejected" and str(note or "").startswith(WITHDRAWN):
        return "withdrawn"
    return status


def batch_outcome(statuses: Iterable[str]) -> str:
    """A decided batch's one line, from its rows' ``card_outcome``s:
    "2 approved, 1 rejected", in ``CARD_STATUS`` order."""
    counts = Counter(statuses)
    return ", ".join(
        f"{counts[status]} {label.lower()}"
        for status, (label, _tone) in CARD_STATUS.items()
        if counts[status]
    )


def card_component(
    tool: str, content: Any
) -> dict[str, Any] | list[dict[str, Any]] | None:
    """The approval cards a queue tool's result names, compact and
    parse-safe: a stored trace's ``component`` and a chat kit's
    ``CardFrame`` both come from here.

    A displayed result is clipped, and a large proposal batch truncates to
    invalid JSON, so a card built by parsing it silently vanished. The card
    needs only identity (the queue is read for the rows), so identity rides
    here, under any cap. A ``pending`` listing carries one per card. A
    card tool says so at registration (``register_tool(cards=)``).
    """
    if tool not in card_tool_names():
        return None
    if isinstance(content, str):
        try:
            data = json.loads(content)
        except (TypeError, ValueError):
            return None
    else:
        data = result_data(content)
    if not isinstance(data, dict) or data.get("error"):
        return None
    if tool == "pending":
        # The listing nominates what to draw (``draw``): only it knows
        # whether the user asked to see a card. A trace kept before it
        # did draws every card it listed, as it did then.
        rows = data.get("draw")
        if rows is None:
            rows = (data.get("pending") or []) + (data.get("decided") or [])
        return _pending_markers(rows) or None
    return _identity_marker(data)


def _pending_markers(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One marker per listed card, in listing order."""
    identities = [
        {
            **card,
            "count": card.get("rows"),
            "pending_change_id": (card.get("pending_change_ids") or [None])[0],
        }
        for card in cards
    ]
    return [m for m in map(_identity_marker, identities) if m is not None]


def _identity_marker(data: dict[str, Any]) -> dict[str, Any] | None:
    if data.get("batch_id"):
        return {
            "kind": "pending_change_batch",
            "batch_id": data["batch_id"],
            "change_type": data.get("change_type"),
            "title": data.get("title"),
            "count": data.get("count"),
        }
    if data.get("pending_change_id"):
        return {
            "kind": "pending_change",
            "pending_change_id": data["pending_change_id"],
            "change_type": data.get("change_type"),
            "title": data.get("title"),
            "status": data.get("status", "pending"),
        }
    return None


def as_markers(component: Any) -> list[dict[str, Any]]:
    """A ``card_component`` (one marker or a listing's several) as a list."""
    markers = component if isinstance(component, list) else [component]
    return [m for m in markers if isinstance(m, dict) and m.get("kind")]


def card_markers(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """The cards a stored trace entry carries: an approval card's marker
    (``card_component``), and the cards a script drew beside it; for an
    entry kept before markers, the card its clipped result names."""
    found = as_markers(entry.get("component"))
    tool, result = entry.get("tool"), entry.get("result")
    if found or tool == "pending" or tool not in card_tool_names():
        return found
    if not isinstance(result, str):
        return []
    try:
        data = json.loads(result)
    except ValueError:
        data = salvage_identity(result)
    marker = _identity_marker(data) if isinstance(data, dict) else None
    return [marker] if marker else []


def salvage_identity(clipped: str) -> dict[str, Any] | None:
    """A proposal's identity from its result clipped to invalid JSON: the
    identity fields lead the result, so they survive the clip."""
    fields: dict[str, Any] = {}
    for key in ("batch_id", "change_type", "title", "status"):
        if found := re.search(rf'"{key}":\s*"([^"]*)"', clipped):
            fields[key] = found.group(1)
    if found := re.search(r'"pending_change_id":\s*(\d+)', clipped):
        fields["pending_change_id"] = int(found.group(1))
    return fields if fields.get("batch_id") or fields.get("pending_change_id") else None


# A reply's steps line (``steps_line``): what its turn DID, replayed with
# the reply in later turns' history. The words alone do not carry the ids a
# turn had in hand and the sandbox resets every turn, so "try again"
# queried for them again. A call's arguments carry those ids, so they get
# the most room; a script's whole entry is clipped, so lookups cannot crowd
# a proposal after them out of the cap.
_STEPS_CAP = 1_200
_STEP_ARGS_CAP = 400
_STEP_SCRIPT_CAP = 240
_STEP_OUTPUT_CAP = 120
_STEP_DISPATCH_CAP = 60


def steps_line(trace: list[dict[str, Any]]) -> str:
    """One capped line saying what each call of a turn did: a call with its
    arguments, a script by the calls it dispatched (else its first line of
    code) and what it printed, and the cards either one named."""
    parts: list[str] = []
    for entry in trace:
        tool = str(entry.get("tool", "?"))
        code = entry.get("code")
        if isinstance(code, str):
            called = ", ".join(
                f"{n.get('tool')}({str(n.get('args') or '')[:_STEP_DISPATCH_CAP]})"
                for n in entry.get("nested") or []
            )
            said = f"{tool}[{called or first_code_line(code)}]"
            if printed := " ".join(trace_output(entry).split()):
                said += f" -> {printed[:_STEP_OUTPUT_CAP]}"
            said = said[:_STEP_SCRIPT_CAP]
        else:
            said = f"{tool}({str(entry.get('args') or '')[:_STEP_ARGS_CAP]})"
        for marker in card_markers(entry):
            card = (
                marker.get("batch_id")
                or marker.get("pending_change_id")
                or marker.get("id")
            )
            if card:
                said += f" -> card {card}"
        parts.append(said)
    return "; ".join(parts)[:_STEPS_CAP]
