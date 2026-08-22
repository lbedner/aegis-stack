"""Tool-calling chat kit — a reusable primitive for streaming, budgeted,
context-aware chat over pydantic-ai.

GENERIC: nothing here knows about metrics, projects, or Pulse. A caller
supplies a persona, context providers, tools, a deps type, and a budget
policy; the kit owns the turn mechanics (context assembly, a bounded tool
loop, streaming frames, exact cost recording). Earmarked to backport to
aegis-stack alongside the htmx/Alpine frontend — see
``docs/aegis-stack-backport.md``.

Public surface:
- ``ToolChatAgent`` — the streaming turn engine.
- ``ContextProvider`` / ``StaticContextProvider`` — per-turn context blocks.
- ``BudgetGuard`` / ``BudgetStatus`` — per-user daily spend control.
- ``ChatScope`` / ``ChatMessage`` — identity + stored-turn value types.
- Frames (``DeltaFrame`` / ``DoneFrame`` / ``BlockedFrame`` / ``ErrorFrame``)
  and ``ndjson_response`` — the streaming output contract.
"""

from .agent import ToolChatAgent, to_model_history
from .budget import BudgetGuard
from .context import (
    ContextProvider,
    StaticContextProvider,
    compose_context,
    gather_context,
)
from .history import ConversationStore
from .models import (
    BlockedFrame,
    BudgetStatus,
    ChatMessage,
    ChatScope,
    DeltaFrame,
    DoneFrame,
    ErrorFrame,
    StreamFrame,
)
from .streaming import ndjson_line, ndjson_response

__all__ = [
    "ToolChatAgent",
    "to_model_history",
    "BudgetGuard",
    "BudgetStatus",
    "ConversationStore",
    "ContextProvider",
    "StaticContextProvider",
    "compose_context",
    "gather_context",
    "ChatScope",
    "ChatMessage",
    "DeltaFrame",
    "DoneFrame",
    "BlockedFrame",
    "ErrorFrame",
    "StreamFrame",
    "ndjson_line",
    "ndjson_response",
]
