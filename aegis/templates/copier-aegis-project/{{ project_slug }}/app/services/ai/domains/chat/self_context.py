"""What the agent can see this turn, as a fact it can be asked for.

An agent's answer is only ever as good as what rode into the model with
it, and until now nothing could say what that was. "Do you still have
the page I pasted?" was unanswerable from the inside: history is
budgeted by SIZE and the oldest turns drop silently, so an agent that
had lost four pasted pages sounded exactly like one that still had them
and found nothing in them.

``record_turn_context`` stamps the assembled shape at the moment the
prompt is built; the ``context`` tool reads it back. The stamp holds
SIZES and COUNTS, never the text - repeating the transcript into the
transcript is how a context report doubles the thing it is reporting on.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field

from app.services.ai.domains.chat.tools import register_tool

# Tokens are model-specific; this is the same 4-chars-per-token rule the
# history budget is computed with, so the two numbers stay comparable.
CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class Block:
    """One labelled slab of the assembled prompt."""

    name: str
    chars: int


@dataclass
class TurnContext:
    """The shape of one turn's context window."""

    model: str = ""
    provider: str = ""
    context_window: int | None = None
    blocks: list[Block] = field(default_factory=list)
    history_chars: int = 0
    history_budget: int = 0
    messages_kept: int = 0
    messages_dropped: int = 0
    tools: list[str] = field(default_factory=list)
    code_mode: bool = False

    @property
    def system_chars(self) -> int:
        return sum(b.chars for b in self.blocks)

    @property
    def total_chars(self) -> int:
        return self.system_chars + self.history_chars


_turn: contextvars.ContextVar[TurnContext | None] = contextvars.ContextVar(
    "turn_context", default=None
)


def begin_turn_context() -> TurnContext:
    """Start a fresh stamp for the turn being assembled.

    Set rather than scoped: prompt assembly and the model run share one
    task, and the next turn's assembly replaces the stamp before anything
    can read a stale one. Nothing outside this module holds the value, so
    there is no window where a reader sees another turn's numbers.
    """
    stamp = TurnContext()
    _turn.set(stamp)
    return stamp


def record_turn_context(**fields: object) -> None:
    """Merge assembled facts into this turn's stamp, if one is open.

    A no-op outside a turn so prompt assembly stays callable from tests
    and one-off scripts without a wrapper.
    """
    stamp = _turn.get()
    if stamp is None:
        return
    for key, value in fields.items():
        setattr(stamp, key, value)


def _tokens(chars: int) -> int:
    return chars // CHARS_PER_TOKEN


async def context() -> str:
    """Report what is in your own context window this turn.

    Answers "what can you still see?" - which instructions, which live
    briefings, how much of this conversation survived the history budget
    and how much fell out of it, and which tools you were granted. Reach
    for it when the user asks what you remember or why you missed
    something they already told you, and SAY the dropped count out loud
    when it is not zero: earlier turns leaving your context is the one
    failure that looks exactly like not finding an answer.
    """
    stamp = _turn.get()
    if stamp is None:
        return "No turn context recorded."

    lines = [f"Model: {stamp.model} ({stamp.provider})"]
    if stamp.context_window:
        lines[0] += f", {stamp.context_window:,}-token window"
    lines.append(
        f"Using about {_tokens(stamp.total_chars):,} tokens of it: "
        f"{_tokens(stamp.system_chars):,} of instructions and briefings, "
        f"{_tokens(stamp.history_chars):,} of this conversation."
    )
    lines.append("")
    lines.append("Instructions and briefings:")
    for block in stamp.blocks:
        lines.append(f"- {block.name}: ~{_tokens(block.chars):,} tokens")
    lines.append("")
    lines.append(
        f"Conversation replayed: {stamp.messages_kept} messages, "
        f"~{_tokens(stamp.history_chars):,} tokens against a budget of "
        f"~{_tokens(stamp.history_budget):,}."
    )
    if stamp.messages_dropped:
        lines.append(
            f"{stamp.messages_dropped} older message(s) did NOT fit and are "
            "not in front of me - anything only stated there is gone."
        )
    else:
        lines.append("Nothing was dropped; the whole conversation is in front of me.")
    if stamp.tools:
        mode = "code mode" if stamp.code_mode else "direct calls"
        lines.append("")
        lines.append(f"Tools ({mode}): {', '.join(stamp.tools)}")
    return "\n".join(lines)


# Built-in registration: importing this module makes the tool grantable
# via the agent registry. replace=True keeps re-imports idempotent.
register_tool(
    "context",
    context,
    description="Report what is in your own context window this turn",
    replace=True,
)
